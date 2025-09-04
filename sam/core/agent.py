import logging
import json
from .tools import ToolRegistry
from .llm_provider import LLMProvider
from .memory import MemoryManager

logger = logging.getLogger(__name__)


class SAMAgent:
    def __init__(self, llm: LLMProvider, tools: ToolRegistry, memory: MemoryManager, system_prompt: str):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.system_prompt = system_prompt

    async def run(self, user_input: str, session_id: str) -> str:
        """Main agent execution loop."""
        logger.info(f"Starting agent run for session {session_id}")
        
        # Load session context
        context = await self.memory.load_session(session_id)
        
        # Build message chain with system prompt
        messages = [{"role": "system", "content": self.system_prompt}] + context + [
            {"role": "user", "content": user_input}
        ]
        
        # Main execution loop
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Agent iteration {iteration} for session {session_id}")
            
            try:
                # Get LLM response with available tools
                resp = await self.llm.chat_completion(messages, tools=self.tools.list_specs())
                
                # Check if LLM wants to call tools
                if hasattr(resp, "tool_calls") and resp.tool_calls:
                    logger.debug(f"LLM requested {len(resp.tool_calls)} tool calls")
                    
                    # Add assistant message with tool calls
                    messages.append({
                        "role": "assistant", 
                        "content": resp.content or "",
                        "tool_calls": resp.tool_calls
                    })
                    
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
                        
                        logger.info(f"Calling tool: {tool_name}")
                        result = await self.tools.call(tool_name, tool_args)
                        
                        # Add tool result to message chain with tool_call_id
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": json.dumps(result) if isinstance(result, dict) else str(result)
                        })
                    
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