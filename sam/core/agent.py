import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional
from .tools import ToolRegistry
from .middleware import ToolContext
from .llm_provider import LLMProvider
from .memory import MemoryManager
from .events import EventBus, get_event_bus
from .context import RequestContext

logger = logging.getLogger(__name__)


def _normalize_user_id(user_id: Optional[str]) -> str:
    if isinstance(user_id, str) and user_id.strip():
        return user_id.strip()
    return "default"


class SAMAgent:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        memory: MemoryManager,
        system_prompt: str,
        event_bus: Optional[EventBus] = None,
    ):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.system_prompt = system_prompt
        self.events = event_bus or get_event_bus()
        self.tool_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None

        # Usage tracking
        self.session_stats = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
            "context_length": 0,
        }

        # Session-based caching for better UX
        self._reset_session_cache()

    async def run(
        self,
        user_input: str,
        session_id: str,
        *,
        publish_final_event: bool = True,
        context: Optional[RequestContext] = None,
    ) -> str:
        """Main agent execution loop."""
        logger.info(f"Starting agent run for session {session_id}")

        user_id = _normalize_user_id(context.user_id if context else None)

        # Signal run start for UIs
        try:
            await self.events.publish(
                "agent.status",
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "state": "start",
                    "message": "Starting",
                },
            )
        except Exception:
            pass

        # Load session context
        history = await self.memory.load_session(session_id, user_id=user_id)

        # Build message chain with system prompt
        messages: List[Dict[str, Any]] = (
            [{"role": "system", "content": self.system_prompt}]
            + history
            + [{"role": "user", "content": user_input}]
        )

        # Guard against repetitive greetings/responses
        try:
            prior_assistant = next(
                (m for m in reversed(history) if m.get("role") == "assistant"),
                None,
            )
            if prior_assistant and prior_assistant.get("content"):
                messages.insert(
                    1,
                    {
                        "role": "system",
                        "content": (
                            "Do not repeat previous greetings or the same reply. "
                            "If a similar instruction was already given earlier in this session, respond directly and proceed with tools."
                        ),
                    },
                )
        except Exception:
            pass

        # Update context length tracking
        self.session_stats["context_length"] = len(messages)

        # Main execution loop - configurable max iterations
        max_iterations = int(os.getenv("SAM_MAX_AGENT_ITERATIONS", "5"))
        iteration = 0

        # Optimization: Cache for serialized results to avoid re-serialization
        serialization_cache: Dict[int, str] = {}

        # Helper to get cached serialized result
        def serialize_result(result: Any) -> str:
            """Serialize result with caching to avoid duplicate JSON encoding."""
            result_id = id(result)
            if result_id in serialization_cache:
                return serialization_cache[result_id]

            serialized = (
                json.dumps(result, default=str) if isinstance(result, dict) else str(result)
            )
            serialization_cache[result_id] = serialized
            return serialized

        tool_call_history: List[tuple[str, str]] = []  # Track tool calls to prevent immediate loops
        tool_call_counts: Dict[str, int] = {}  # Track calls per tool name
        error_count = 0  # Track consecutive tool errors

        # Optimization: Batch events to reduce async overhead
        pending_events: List[tuple[str, Dict[str, Any]]] = []

        async def flush_events() -> None:
            """Publish all pending events in batch."""
            if not pending_events:
                return
            try:
                # Publish events concurrently
                await asyncio.gather(
                    *[
                        self.events.publish(event_name, payload)
                        for event_name, payload in pending_events
                    ],
                    return_exceptions=True,
                )
            except Exception:
                pass
            finally:
                pending_events.clear()

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Agent iteration {iteration} for session {session_id}")

            try:
                # Get LLM response with available tools
                # Batch thinking status event
                pending_events.append(
                    (
                        "agent.status",
                        {
                            "session_id": session_id,
                            "user_id": user_id,
                            "state": "thinking",
                            "message": "Thinking",
                            "iteration": iteration,
                        },
                    )
                )
                await flush_events()
                # Pass a copy to avoid later mutations (we append to messages after the call)
                resp = await self.llm.chat_completion(list(messages), tools=self.tools.list_specs())

                # Track token usage
                if resp.usage:
                    self.session_stats["requests"] += 1
                    self.session_stats["prompt_tokens"] += resp.usage.get("prompt_tokens", 0)
                    self.session_stats["completion_tokens"] += resp.usage.get(
                        "completion_tokens", 0
                    )
                    self.session_stats["total_tokens"] += resp.usage.get("total_tokens", 0)

                # Check if LLM wants to call tools
                # Batch token usage event if available
                if resp.usage:
                    pending_events.append(
                        (
                            "llm.usage",
                            {
                                "session_id": session_id,
                                "user_id": user_id,
                                "usage": resp.usage,
                                "context_length": self.session_stats.get("context_length", 0),
                            },
                        )
                    )

                if hasattr(resp, "tool_calls") and resp.tool_calls:
                    logger.debug(f"LLM requested {len(resp.tool_calls)} tool calls")

                    # Add assistant message with tool calls
                    assistant_message: Dict[str, Any] = {
                        "role": "assistant",
                        "content": resp.content or "",
                    }
                    assistant_message["tool_calls"] = resp.tool_calls
                    messages.append(assistant_message)

                    # Execute each tool call
                    for call in resp.tool_calls:
                        tool_name = call.get("function", {}).get("name", "")
                        tool_args_str = call.get("function", {}).get("arguments", "{}")
                        tool_call_id = call.get("id", "")

                        # Parse arguments as JSON string (OpenAI format)
                        try:
                            tool_args = json.loads(tool_args_str)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse tool arguments as JSON: {e}")
                            tool_args = {}

                        # Check for excessive tool calls (prevent spam)
                        call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))

                        # Track per-tool call counts
                        tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1

                        # Define strict limits per tool type
                        max_calls_per_tool = {
                            # Info tools: only 1 call needed (they return complete data)
                            "get_balance": 1,
                            "get_token_info": 1,
                            "get_pump_token_info": 1,
                            "get_token_data": 1,
                            # Trading tools: allow 2 calls max
                            "hyperliquid_market_order": 2,
                            "hyperliquid_close_position": 2,
                            "pump_fun_buy": 2,
                            "pump_fun_sell": 2,
                            "jupiter_swap": 2,
                            "smart_buy": 2,
                            # Default: 2 calls max for any tool
                        }

                        limit = max_calls_per_tool.get(tool_name, 2)

                        if tool_call_counts[tool_name] > limit:
                            logger.warning(
                                f"Tool {tool_name} exceeded call limit ({tool_call_counts[tool_name]} > {limit})"
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": tool_name,
                                    "content": json.dumps(
                                        {
                                            "error": "TOOL_CALL_LIMIT_EXCEEDED",
                                            "message": f"Tool '{tool_name}' was called {tool_call_counts[tool_name]} times (limit: {limit}). Use previous results.",
                                            "instructions": "Provide a final answer based on information you already have. Do not call this tool again.",
                                        }
                                    ),
                                }
                            )
                            continue

                        # Track this tool call
                        tool_call_history.append(call_signature)
                        # Keep only last 5 calls in history
                        if len(tool_call_history) > 5:
                            tool_call_history.pop(0)

                        # Auto-fill missing required args for certain tools
                        try:
                            if tool_name in {"search_web", "search_news"}:
                                q = str(tool_args.get("query", "")).strip()
                                if not q:
                                    # Use the current user_input as a sensible default
                                    tool_args["query"] = (user_input or "").strip()[:256]
                                    logger.debug(
                                        f"Filled missing 'query' for {tool_name} from user input"
                                    )
                        except Exception:
                            pass

                        logger.info(f"Calling tool: {tool_name}")
                        # Batch tool events for better performance
                        pending_events.append(
                            (
                                "tool.called",
                                {
                                    "session_id": session_id,
                                    "user_id": user_id,
                                    "name": tool_name,
                                    "args": tool_args,
                                    "tool_call_id": tool_call_id,
                                },
                            )
                        )
                        pending_events.append(
                            (
                                "agent.status",
                                {
                                    "session_id": session_id,
                                    "user_id": user_id,
                                    "state": "tool_call",
                                    "name": tool_name,
                                    "message": f"Calling {tool_name}",
                                },
                            )
                        )

                        # Notify CLI about tool usage if callback is set
                        if self.tool_callback:
                            self.tool_callback(tool_name, tool_args)

                        result = await self.tools.call(
                            tool_name, tool_args, context=ToolContext(session_id=session_id)
                        )

                        # Determine success/failure in a normalized way
                        is_success = False
                        if isinstance(result, dict):
                            if "success" in result:
                                is_success = bool(result.get("success"))
                            else:
                                is_success = "error" not in result

                        # Check if tool returned an error and categorize it
                        error_type = "unknown"
                        error_details = {}

                        if not is_success:
                            # Automatic fallback: if pump.fun buy failed, try Jupiter swap
                            try:
                                if tool_name == "pump_fun_buy":
                                    # Batch fallback status event
                                    pending_events.append(
                                        (
                                            "agent.status",
                                            {
                                                "session_id": session_id,
                                                "user_id": user_id,
                                                "state": "fallback",
                                                "message": "pump.fun failed — trying Jupiter",
                                            },
                                        )
                                    )
                                    await flush_events()

                                    wsol = "So11111111111111111111111111111111111111112"
                                    out_mint = str(tool_args.get("mint", ""))
                                    amount_sol = float(tool_args.get("amount", 0))
                                    slippage_pct = int(tool_args.get("slippage", 5) or 5)
                                    amount_lamports = max(0, int(amount_sol * 1_000_000_000))
                                    slippage_bps = max(1, min(1000, slippage_pct * 100))

                                    jup_args = {
                                        "input_mint": wsol,
                                        "output_mint": out_mint,
                                        "amount": amount_lamports,
                                        "slippage_bps": slippage_bps,
                                    }

                                    # Batch fallback tool call event
                                    pending_events.append(
                                        (
                                            "tool.called",
                                            {
                                                "session_id": session_id,
                                                "user_id": user_id,
                                                "name": "jupiter_swap",
                                                "args": jup_args,
                                                "tool_call_id": f"fallback-{tool_call_id}",
                                            },
                                        )
                                    )

                                    jup_res = await self.tools.call(
                                        "jupiter_swap",
                                        jup_args,
                                        context=ToolContext(session_id=session_id),
                                    )

                                    # Append tool result into the transcript so the model can continue
                                    messages.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": f"fallback-{tool_call_id}",
                                            "name": "jupiter_swap",
                                            "content": serialize_result(jup_res),
                                        }
                                    )

                                    # Batch fallback result events
                                    jup_success = isinstance(jup_res, dict) and (
                                        jup_res.get("success") is True or "error" not in jup_res
                                    )
                                    event_name = "tool.succeeded" if jup_success else "tool.failed"
                                    pending_events.append(
                                        (
                                            event_name,
                                            {
                                                "session_id": session_id,
                                                "user_id": user_id,
                                                "name": "jupiter_swap",
                                                "args": jup_args,
                                                "result": jup_res,
                                                "tool_call_id": f"fallback-{tool_call_id}",
                                            },
                                        )
                                    )

                                    # Continue loop to let the model react to the fallback result
                                    error_count = 0
                                    continue
                            except Exception:
                                # Fallback attempt errors are non-fatal; proceed with normal handling
                                pass

                            error_count += 1
                            # Batch failure event
                            pending_events.append(
                                (
                                    "tool.failed",
                                    {
                                        "session_id": session_id,
                                        "user_id": user_id,
                                        "name": tool_name,
                                        "args": tool_args,
                                        "result": result,
                                        "tool_call_id": tool_call_id,
                                    },
                                )
                            )

                            # Detect structured error format
                            if isinstance(result.get("error"), bool) and result.get("error"):
                                # This is a UserFriendlyError structure
                                error_type = result.get("category", "unknown")
                                error_details = {
                                    "title": result.get("title", "Error"),
                                    "message": result.get("message", "Unknown error"),
                                    "solutions": result.get("solutions", []),
                                    "category": result.get("category", "unknown"),
                                }
                                logger.warning(
                                    f"Tool {tool_name} error [{error_type}]: {error_details['title']} - {error_details['message']}"
                                )
                            else:
                                # Simple error string
                                error_msg = (
                                    str(result.get("error", "Unknown error"))
                                    if isinstance(result, dict)
                                    else "Unknown error"
                                )
                                logger.warning(f"Tool {tool_name} returned error: {error_msg}")

                                # Categorize based on error content
                                error_msg_lower = error_msg.lower()
                                if "insufficient" in error_msg_lower and (
                                    "balance" in error_msg_lower or "funds" in error_msg_lower
                                ):
                                    error_type = "insufficient_balance"
                                    error_details = {"message": error_msg, "type": "balance"}
                                elif (
                                    "validation" in error_msg_lower or "invalid" in error_msg_lower
                                ):
                                    error_type = "validation"
                                    error_details = {"message": error_msg, "type": "validation"}
                                elif (
                                    "network" in error_msg_lower
                                    or "connection" in error_msg_lower
                                    or "timeout" in error_msg_lower
                                ):
                                    error_type = "network"
                                    error_details = {"message": error_msg, "type": "network"}
                                else:
                                    error_details = {"message": error_msg, "type": "general"}

                            # Add tool result FIRST to satisfy OpenAI's message format requirements
                            # (tool messages must immediately follow assistant message with tool_calls)
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": tool_name,
                                    "content": serialize_result(result),
                                }
                            )

                            # Now add guidance as system messages AFTER the tool response
                            guidance_message: Optional[str] = None
                            if error_type == "validation":
                                missing: List[str] = []
                                if isinstance(result, dict):
                                    details = result.get("details") or {}
                                    if isinstance(details, dict) and isinstance(
                                        details.get("missing_fields"), list
                                    ):
                                        missing_fields = details.get("missing_fields")
                                        if isinstance(missing_fields, list):
                                            missing = missing_fields
                                missing_text = (
                                    f" Missing fields: {', '.join(missing)}." if missing else ""
                                )
                                guidance_message = (
                                    f"TOOL VALIDATION ERROR: {error_details.get('message', '')}{missing_text}"
                                    " You must gather the required parameters from the user or summarize"
                                    " the plan before retrying. Do not claim the action succeeded until"
                                    " the tool returns a success response."
                                )
                            elif error_type == "insufficient_balance":
                                guidance_message = (
                                    "TOOL BALANCE ERROR: The operation failed due to insufficient funds."
                                    " Explain the issue, include the required amount if known, and suggest"
                                    " next steps instead of retrying immediately."
                                )
                            elif error_type == "network":
                                guidance_message = (
                                    "TOOL NETWORK ERROR: There was a connectivity problem. Inform the user"
                                    " and suggest trying again later rather than claiming success."
                                )
                            else:
                                guidance_message = (
                                    f"TOOL ERROR: {error_details.get('message', 'Unknown error')}"
                                    " Do not state that the action completed. Provide the error details"
                                    " to the user and propose what to do next."
                                )

                            if guidance_message:
                                messages.append({"role": "system", "content": guidance_message})

                            # Provide specific guidance based on error type
                            if error_count >= 3:
                                logger.warning(
                                    f"Too many consecutive tool errors ({error_count}), stopping tool calls"
                                )

                                # Create specific guidance based on error type
                                if error_type == "insufficient_balance" or error_type == "wallet":
                                    guidance = f"BALANCE ERROR: The user doesn't have enough SOL for transactions. Current error: {error_details.get('message', 'Insufficient balance')}. INSTRUCTIONS: 1) Explain the balance issue clearly, 2) Tell them exactly how much they need vs what they have, 3) Suggest checking balance or adding funds, 4) DO NOT attempt any more transactions or balance checks."
                                elif error_type == "validation":
                                    guidance = f"VALIDATION ERROR: Invalid input parameters. Error: {error_details.get('message', 'Validation failed')}. INSTRUCTIONS: 1) Explain what input was invalid, 2) Provide correct format examples, 3) DO NOT retry the same operation with invalid parameters."
                                elif error_type == "network":
                                    guidance = f"NETWORK ERROR: Connection or service issue. Error: {error_details.get('message', 'Network error')}. INSTRUCTIONS: 1) Explain the network/service issue, 2) Suggest trying again later, 3) DO NOT immediately retry the same operation."
                                else:
                                    guidance = f"MULTIPLE ERRORS: Several tool operations failed. Last error: {error_details.get('message', 'Unknown error')}. INSTRUCTIONS: 1) Explain what went wrong, 2) Provide alternative suggestions, 3) DO NOT make any more tool calls."

                                messages.append({"role": "system", "content": guidance})

                            # Skip adding tool result again below since we already added it
                            continue_to_next_iteration = True
                        else:
                            error_count = 0  # Reset error count on successful tool call
                            # Batch success events
                            pending_events.append(
                                (
                                    "tool.succeeded",
                                    {
                                        "session_id": session_id,
                                        "user_id": user_id,
                                        "name": tool_name,
                                        "args": tool_args,
                                        "result": result,
                                        "tool_call_id": tool_call_id,
                                    },
                                )
                            )
                            pending_events.append(
                                (
                                    "agent.status",
                                    {
                                        "session_id": session_id,
                                        "user_id": user_id,
                                        "state": "tool_done",
                                        "name": tool_name,
                                        "message": f"{tool_name} done",
                                    },
                                )
                            )

                            continue_to_next_iteration = False

                        # Add tool result to message chain with tool_call_id (for success case only)
                        # Error case already added the tool message above
                        if not continue_to_next_iteration:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": tool_name,
                                    "content": serialize_result(result),
                                }
                            )

                    # Flush batched events after tool execution
                    await flush_events()

                    # Continue the loop to process tool results
                    continue
                else:
                    # No tool calls - this is the final response
                    logger.info(f"Agent completed for session {session_id}")

                    # Save session context (excluding system prompt) WITHOUT final assistant
                    # to match expected behavior in tests and avoid mutating the prompt list
                    await self.memory.save_session(session_id, messages[1:], user_id=user_id)

                    # Update context length tracking (based on messages passed to LLM)
                    try:
                        self.session_stats["context_length"] = len(messages)
                    except Exception:
                        pass

                    # Batch completion events
                    pending_events.append(
                        (
                            "agent.status",
                            {
                                "session_id": session_id,
                                "user_id": user_id,
                                "state": "finish",
                                "message": "Finished",
                            },
                        )
                    )

                    # Optionally publish final assistant message event for UI adapters
                    if publish_final_event:
                        pending_events.append(
                            (
                                "agent.message",
                                {
                                    "session_id": session_id,
                                    "user_id": user_id,
                                    "content": resp.content or "",
                                    "usage": dict(self.session_stats),
                                },
                            )
                        )

                    # Flush all pending events before returning
                    await flush_events()

                    return resp.content or "No response generated"

            except Exception as e:
                logger.error(f"Error in agent execution: {e}")
                return f"I encountered an error: {str(e)}"

        # If we hit max iterations, return current response
        logger.warning(f"Agent hit max iterations ({max_iterations}) for session {session_id}")
        return "I've reached the maximum number of processing steps. Please try rephrasing your request."

    async def clear_context(self, session_id: str, user_id: Optional[str] = None) -> str:
        """Clear conversation context for a session."""
        uid = _normalize_user_id(user_id)
        await self.memory.clear_session(session_id, user_id=uid)

        # Reset stats
        self.session_stats = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
            "context_length": 0,
        }

        self._reset_session_cache()

        try:
            await self.events.publish(
                "agent.status",
                {
                    "session_id": session_id,
                    "user_id": uid,
                    "state": "context_cleared",
                    "message": "Conversation context cleared",
                },
            )
        except Exception:
            pass

        logger.info(f"Cleared context for session {session_id} (user {uid})")
        return "Context cleared! Starting fresh conversation."

    async def compact_conversation(
        self, session_id: str, keep_recent: int = 4, user_id: Optional[str] = None
    ) -> str:
        """Compact the conversation by summarizing older messages.

        Args:
            session_id: Conversation session identifier
            keep_recent: Number of most recent messages to retain after the summary
                          (default 4). Set to 0 to keep only the summary.
        """
        uid = _normalize_user_id(user_id)
        history = await self.memory.load_session(session_id, user_id=uid)

        if len(history) <= max(keep_recent + 2, 6):  # small conversations are already compact
            return "Conversation is already compact (≤6 messages)."

        # Keep the last N messages and summarize the rest
        k = max(0, int(keep_recent))
        recent_messages = history[-k:] if k > 0 else []
        old_messages = history[:-k] if k > 0 else history

        if not old_messages:
            return "Nothing to compact."

        # Create summary prompt
        summary_prompt = f"""Summarize this conversation history in 2-3 bullet points, focusing on key decisions, transactions, and context that would be useful for future interactions:

{self._format_messages_for_summary(old_messages)}

Respond with just the bullet points, no preamble."""

        # Get summary from LLM
        summary_messages = [{"role": "user", "content": summary_prompt}]
        resp = await self.llm.chat_completion(summary_messages)
        summary = resp.content.strip()

        # Create new compact context
        compact_context = [
            {"role": "assistant", "content": f"📋 **Previous conversation summary:**\n{summary}"}
        ] + recent_messages

        # Save compacted context
        await self.memory.save_session(session_id, compact_context, user_id=uid)

        # Update context length
        self.session_stats["context_length"] = len(compact_context) + 1  # +1 for system prompt

        logger.info(
            f"Compacted session {session_id} (user {uid}): {len(old_messages)} → summary + {len(recent_messages)} messages"
        )
        return f"Conversation compacted! Summarized {len(old_messages)} old messages, kept {len(recent_messages)} recent ones."

    def _format_messages_for_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Format messages for summary prompt."""
        formatted = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                formatted.append(f"User: {content}")
            elif role == "assistant":
                formatted.append(f"Assistant: {content}")
            elif role == "tool":
                tool_name = msg.get("name", "tool")
                formatted.append(f"[{tool_name} executed]")
        return "\n".join(formatted)

    def is_balance_fresh(self) -> bool:
        """Check if cached balance data is still fresh (< 60 seconds)."""
        balance_updated = self.session_cache["balance_updated"]
        return (
            self.session_cache["balance_data"] is not None
            and time.time() - float(balance_updated) < 60
        )

    def cache_balance_data(self, balance_data: Dict[str, Any]) -> None:
        """Cache balance data with timestamp."""
        self.session_cache["balance_data"] = balance_data
        self.session_cache["balance_updated"] = time.time()

    def get_cached_balance(self) -> Optional[Dict[str, Any]]:
        """Get cached balance data if fresh, otherwise None."""
        cached_data = self.session_cache["balance_data"]
        return cached_data if self.is_balance_fresh() else None

    def cache_token_metadata(self, mint: str, metadata: Dict[str, Any]) -> None:
        """Cache token metadata (persists for session lifetime)."""
        metadata_cache = self.session_cache["token_metadata"]
        if isinstance(metadata_cache, dict):
            metadata_cache[mint] = metadata

    def get_cached_token_metadata(self, mint: str) -> Optional[Dict[str, Any]]:
        """Get cached token metadata."""
        metadata_cache = self.session_cache["token_metadata"]
        return metadata_cache.get(mint) if isinstance(metadata_cache, dict) else None

    def invalidate_balance_cache(self) -> None:
        """Invalidate balance cache after transactions."""
        self.session_cache["balance_data"] = None
        self.session_cache["balance_updated"] = 0

    def _reset_session_cache(self) -> None:
        self.session_cache: Dict[str, Any] = {
            "balance_data": None,
            "balance_updated": 0.0,
            "token_metadata": {},  # {mint: metadata_dict}
        }

    async def close(self) -> None:
        """Close any resources owned or referenced by this agent.

        Best-effort and safe to call multiple times.
        """
        # Close Solana client if present
        try:
            st = getattr(self, "_solana_tools", None)
            if st and hasattr(st, "close"):
                await st.close()
        except Exception:
            pass

        # Close LLM provider if it exposes close (no-op for shared HTTP client)
        try:
            if self.llm and hasattr(self.llm, "close"):
                await self.llm.close()
        except Exception:
            pass

        # Nothing to do for ToolRegistry/memory; shared utilities have their own cleanup
