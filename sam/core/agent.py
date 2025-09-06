import logging
import json
import time
from typing import Optional, Callable, List, Dict, Any
from .tools import ToolRegistry
from .llm_provider import LLMProvider
from .memory import MemoryManager

logger = logging.getLogger(__name__)


class SAMAgent:
    def __init__(
        self, llm: LLMProvider, tools: ToolRegistry, memory: MemoryManager, system_prompt: str
    ):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.system_prompt = system_prompt
        self.tool_callback: Optional[Callable] = None  # For CLI tool usage feedback

        # Usage tracking
        self.session_stats = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
            "context_length": 0,
        }

        # Session-based caching for better UX
        self.session_cache: Dict[str, Any] = {
            "balance_data": None,
            "balance_updated": 0,
            "token_metadata": {},  # {mint: metadata_dict}
        }

    async def run(self, user_input: str, session_id: str) -> str:
        """Main agent execution loop."""
        logger.info(f"Starting agent run for session {session_id}")

        # Load session context
        context = await self.memory.load_session(session_id)

        # Build message chain with system prompt
        messages = (
            [{"role": "system", "content": self.system_prompt}]
            + context
            + [{"role": "user", "content": user_input}]
        )

        # Update context length tracking
        self.session_stats["context_length"] = len(messages)

        # Main execution loop
        max_iterations = 5  # Reduced to prevent infinite loops more aggressively
        iteration = 0
        tool_call_history: List[tuple[str, str]] = []  # Track tool calls to prevent immediate loops

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Agent iteration {iteration} for session {session_id}")

            try:
                # Get LLM response with available tools
                resp = await self.llm.chat_completion(messages, tools=self.tools.list_specs())

                # Track token usage
                if resp.usage:
                    self.session_stats["requests"] += 1
                    self.session_stats["prompt_tokens"] += resp.usage.get("prompt_tokens", 0)
                    self.session_stats["completion_tokens"] += resp.usage.get(
                        "completion_tokens", 0
                    )
                    self.session_stats["total_tokens"] += resp.usage.get("total_tokens", 0)

                # Check if LLM wants to call tools
                if hasattr(resp, "tool_calls") and resp.tool_calls:
                    logger.debug(f"LLM requested {len(resp.tool_calls)} tool calls")

                    # Add assistant message with tool calls
                    messages.append(
                        {
                            "role": "assistant",
                            "content": resp.content or "",
                            "tool_calls": resp.tool_calls,
                        }
                    )

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

                        # Check for immediate repetitive calls (more aggressive prevention)
                        call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))

                        # Prevent any tool from being called more than once with same args
                        if call_signature in tool_call_history:
                            logger.warning(f"Preventing duplicate tool call: {tool_name}")
                            # Add a synthetic result to break the loop
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": tool_name,
                                    "content": json.dumps(
                                        {
                                            "error": "TOOL_ALREADY_CALLED",
                                            "message": f"The tool '{tool_name}' was already called in this conversation. Use the previous result instead of calling it again.",
                                            "instructions": "Please provide a response based on the previous tool result rather than making another call.",
                                        }
                                    ),
                                }
                            )
                            continue

                        # Also check for balance-specific loops (even stricter)
                        if tool_name == "get_balance":
                            balance_calls = [
                                sig for sig in tool_call_history if sig[0] == "get_balance"
                            ]
                            if len(balance_calls) >= 1:
                                logger.warning(
                                    f"Preventing balance loop - already called {len(balance_calls)} times"
                                )
                                # Insert a strong system message to stop the loop
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": "STOP: You already called get_balance() in this conversation. The previous result contains all wallet information. DO NOT call get_balance() again. Use the previous result to answer the user's question about their balance.",
                                    }
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "content": json.dumps(
                                            {
                                                "error": "BALANCE_ALREADY_CHECKED",
                                                "message": "Balance was already checked in this conversation. The previous balance result contains all wallet information including SOL balance, tokens, and wallet address.",
                                                "instructions": "Use the previous balance data to answer the user's question. Do not call get_balance again.",
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

                        logger.info(f"Calling tool: {tool_name}")

                        # Notify CLI about tool usage if callback is set
                        if self.tool_callback:
                            self.tool_callback(tool_name, tool_args)

                        result = await self.tools.call(tool_name, tool_args)

                        # Add tool result to message chain with tool_call_id
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "content": json.dumps(result)
                                if isinstance(result, dict)
                                else str(result),
                            }
                        )

                    # Continue the loop to process tool results
                    continue
                else:
                    # No tool calls - this is the final response
                    logger.info(f"Agent completed for session {session_id}")

                    # Save session context (excluding system prompt)
                    await self.memory.save_session(session_id, messages[1:])

                    return resp.content or "No response generated"

            except Exception as e:
                logger.error(f"Error in agent execution: {e}")
                return f"I encountered an error: {str(e)}"

        # If we hit max iterations, return current response
        logger.warning(f"Agent hit max iterations ({max_iterations}) for session {session_id}")
        return "I've reached the maximum number of processing steps. Please try rephrasing your request."

    async def clear_context(self, session_id: str) -> str:
        """Clear conversation context for a session."""
        await self.memory.clear_session(session_id)

        # Reset stats
        self.session_stats = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "requests": 0,
            "context_length": 0,
        }

        logger.info(f"Cleared context for session {session_id}")
        return "Context cleared! Starting fresh conversation."

    async def compact_conversation(self, session_id: str) -> str:
        """Compact the conversation by summarizing older messages."""
        context = await self.memory.load_session(session_id)

        if len(context) <= 6:  # Keep if already short
            return "Conversation is already compact (≤6 messages)."

        # Keep the last 4 messages and summarize the rest
        recent_messages = context[-4:]
        old_messages = context[:-4]

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
            {"role": "assistant", "content": f"📋 **Previous conversation summary:**\n{summary}"},
            {"role": "user", "content": "---"},
        ] + recent_messages

        # Save compacted context
        await self.memory.save_session(session_id, compact_context)

        # Update context length
        self.session_stats["context_length"] = len(compact_context) + 1  # +1 for system prompt

        logger.info(
            f"Compacted session {session_id}: {len(old_messages)} → summary + {len(recent_messages)} messages"
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
