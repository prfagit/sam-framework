from typing import Any, Dict, List, Optional
import aiohttp
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class ChatResponse:
    def __init__(self, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None):
        self.content = content
        self.tool_calls = tool_calls or []


class LLMProvider:
    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self._session = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the HTTP session with proper timeout and settings."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
        
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
        
    async def chat_completion(
        self, 
        messages: List[Dict[str, Any]], 
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatResponse:
        """Make a chat completion request to the LLM provider."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages
        }
        
        # Add tools if provided, converting to OpenAI function format
        if tools:
            formatted_tools = []
            for tool in tools:
                # Extract parameters from input_schema (OpenAI expects just the JSON schema)
                input_schema = tool["input_schema"]
                parameters = input_schema.get("parameters") if isinstance(input_schema, dict) else input_schema
                
                function_def = {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": parameters
                }
                formatted_tools.append({"type": "function", "function": function_def})
            
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"
        
        logger.debug(f"Sending chat completion request to {self.base_url}/chat/completions")
        
        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries + 1):
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extract response data
                        if "choices" not in data or not data["choices"]:
                            raise Exception("No choices in LLM response")
                        
                        choice = data["choices"][0]["message"]
                        # Some providers return explicit null for content when using tools
                        raw_content = choice.get("content")
                        content = raw_content if isinstance(raw_content, str) else ""
                        tool_calls = choice.get("tool_calls") or []
                        
                        content_len = len(content) if isinstance(content, str) else 0
                        logger.debug(f"LLM response: content_length={content_len}, tool_calls={len(tool_calls)}")
                        
                        return ChatResponse(content=content, tool_calls=tool_calls)
                    
                    # Handle server errors with retry
                    elif response.status >= 500:
                        error_text = await response.text()
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"LLM API server error {response.status}, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1})")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise Exception(f"LLM API server error {response.status}: {error_text}")
                    
                    # Client errors - don't retry
                    else:
                        error_text = await response.text()
                        logger.error(f"LLM API error {response.status}: {error_text}")
                        raise Exception(f"LLM API error {response.status}: {error_text}")
                        
            except aiohttp.ClientError as e:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Network error in LLM request, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1}): {e}")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"HTTP error in LLM request after all retries: {e}")
                    raise Exception(f"Network error: {str(e)}")
                    
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in LLM response: {e}")
                raise Exception(f"Invalid JSON response: {str(e)}")
                
            except Exception as e:
                # For non-retryable errors, fail immediately
                if "choices" in str(e) or "Invalid JSON" in str(e):
                    logger.error(f"LLM response error: {e}")
                    raise
                    
                # For other errors, retry if we have attempts left
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Unexpected error in LLM request, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1}): {e}")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Unexpected error in LLM request after all retries: {e}")
                    raise
        
        # This should never be reached due to the raise statements above
        raise Exception("Maximum retries exceeded for LLM request")
