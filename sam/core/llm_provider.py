from typing import Any, Dict, List, Optional
import aiohttp
import asyncio
import json
import logging
from ..utils.http_client import get_session
from ..config.settings import Settings
from importlib.metadata import entry_points

logger = logging.getLogger(__name__)


class ChatResponse:
    def __init__(
        self,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        usage: Optional[Dict[str, Any]] = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage or {}


class LLMProvider:
    """Abstract-ish base for LLM providers."""

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def close(self):
        """Close method for compatibility - shared client handles cleanup."""
        pass  # Shared HTTP client handles session lifecycle

    async def chat_completion(
        self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatResponse:
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI and OpenAI-compatible chat APIs (tool calling)."""

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url or "https://api.openai.com/v1")

    async def chat_completion(
        self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatResponse:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        payload: Dict[str, Any] = {"model": self.model, "messages": messages}

        # Add tools if provided, converting to OpenAI function format
        if tools:
            formatted_tools = []
            for tool in tools:
                input_schema = tool["input_schema"]
                parameters = (
                    input_schema.get("parameters")
                    if isinstance(input_schema, dict)
                    else input_schema
                )
                function_def = {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": parameters,
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
                session = await get_session()
                async with session.post(
                    f"{self.base_url}/chat/completions", headers=headers, json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        if "choices" not in data or not data["choices"]:
                            raise Exception("No choices in LLM response")

                        choice = data["choices"][0]["message"]
                        raw_content = choice.get("content")
                        content = raw_content if isinstance(raw_content, str) else ""
                        tool_calls = choice.get("tool_calls") or []
                        usage = data.get("usage", {})

                        content_len = len(content) if isinstance(content, str) else 0
                        logger.debug(
                            f"LLM response: content_length={content_len}, tool_calls={len(tool_calls)}"
                        )

                        return ChatResponse(content=content, tool_calls=tool_calls, usage=usage)

                    elif response.status >= 500:
                        error_text = await response.text()
                        if attempt < max_retries:
                            delay = base_delay * (2**attempt)
                            logger.warning(
                                f"LLM API server error {response.status}, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise Exception(f"LLM API server error {response.status}: {error_text}")

                    else:
                        error_text = await response.text()
                        logger.error(f"LLM API error {response.status}: {error_text}")
                        raise Exception(f"LLM API error {response.status}: {error_text}")

            except aiohttp.ClientError as e:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Network error in LLM request, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"HTTP error in LLM request after all retries: {e}")
                    raise Exception(f"Network error: {str(e)}")

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in LLM response: {e}")
                raise Exception(f"Invalid JSON response: {str(e)}")

            except Exception as e:
                if "choices" in str(e) or "Invalid JSON" in str(e):
                    logger.error(f"LLM response error: {e}")
                    raise

                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Unexpected error in LLM request, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Unexpected error in LLM request after all retries: {e}")
                    raise

        raise Exception("Maximum retries exceeded for LLM request")


class XAIProvider(OpenAICompatibleProvider):
    """Provider specifically for xAI Grok API with its own tool calling format."""

    async def chat_completion(
        self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatResponse:
        payload: Dict[str, Any] = {"model": self.model, "messages": messages}

        # Format tools for xAI - they may have stricter requirements
        if tools:
            formatted_tools = []
            for tool in tools:
                input_schema = tool["input_schema"]
                parameters = (
                    input_schema.get("parameters")
                    if isinstance(input_schema, dict)
                    else input_schema
                )

                # Clean up parameters to ensure xAI compatibility
                if isinstance(parameters, dict):
                    # Remove any null references or complex schemas that might cause issues
                    cleaned_params = self._clean_parameters(parameters)

                    function_def = {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": cleaned_params,
                    }
                    formatted_tools.append({"type": "function", "function": function_def})

            if formatted_tools:
                payload["tools"] = formatted_tools
                payload["tool_choice"] = "auto"

        logger.debug(f"Sending xAI chat completion request to {self.base_url}/chat/completions")

        # Use the parent's retry logic but with our custom payload
        return await self._make_request(payload)

    def _clean_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Clean parameter schema for xAI compatibility."""
        if not isinstance(parameters, dict):
            return parameters

        cleaned = {}
        for key, value in parameters.items():
            if key == "$defs":
                continue  # Skip $defs as they might cause issues
            elif key == "anyOf" and isinstance(value, list):
                # Simplify anyOf structures
                if len(value) == 1 and "$ref" in value[0]:
                    continue  # Skip complex references
                cleaned[key] = value
            elif isinstance(value, dict):
                cleaned[key] = self._clean_parameters(value)  # type: ignore
            elif isinstance(value, list):
                cleaned[key] = [
                    self._clean_parameters(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                cleaned[key] = value
        return cleaned

    async def _make_request(self, payload: Dict[str, Any]) -> ChatResponse:
        """Make the actual HTTP request with retry logic."""
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                session = await get_session()
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        if "choices" not in data or not data["choices"]:
                            raise Exception("No choices in xAI response")

                        choice = data["choices"][0]["message"]
                        raw_content = choice.get("content")
                        content = raw_content if isinstance(raw_content, str) else ""
                        tool_calls = choice.get("tool_calls") or []
                        usage = data.get("usage", {})

                        content_len = len(content) if isinstance(content, str) else 0
                        logger.debug(
                            f"xAI response: content_length={content_len}, tool_calls={len(tool_calls)}"
                        )

                        return ChatResponse(content=content, tool_calls=tool_calls, usage=usage)

                    else:
                        error_text = await response.text()
                        logger.error(f"xAI API error {response.status}: {error_text}")

                        if attempt < max_retries and response.status >= 500:
                            delay = base_delay * (2**attempt)
                            logger.warning(f"xAI server error, retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise Exception(f"xAI API error {response.status}: {error_text}")

            except Exception as e:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(f"xAI request error, retrying in {delay}s...: {e}")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"xAI request failed after all retries: {e}")
                    raise

        raise Exception("Maximum retries exceeded for xAI request")


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Messages API with tool use."""

    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        super().__init__(api_key, model, base_url or "https://api.anthropic.com")

    def _format_tools(
        self, tools: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        formatted = []
        for tool in tools:
            # Anthropic expects input_schema at top-level of the tool specification
            input_schema = tool.get("input_schema")

            # Handle different input_schema formats:
            # 1. Direct schema: {"type": "object", "properties": {...}}
            # 2. Nested schema: {"parameters": {"type": "object", ...}}
            if isinstance(input_schema, dict):
                if "parameters" in input_schema:
                    # Format 2: Extract the nested parameters
                    schema = input_schema["parameters"]
                else:
                    # Format 1: Use directly, but ensure it has required fields
                    schema = input_schema

                # Ensure the schema has a type field (required by Anthropic)
                if "type" not in schema:
                    schema = {"type": "object", **schema}
            else:
                # Fallback for unexpected formats
                schema = {"type": "object", "properties": {}}

            formatted.append(
                {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "input_schema": schema,
                }
            )
        return formatted

    def _convert_messages(self, messages: List[Dict[str, Any]]):
        system_parts: List[str] = []
        anth_messages: List[Dict[str, Any]] = []

        # Helper to append a message
        def add_msg(role: str, blocks: List[Dict[str, Any]]):
            if blocks:
                anth_messages.append({"role": role, "content": blocks})

        # Iterate and convert with better grouping
        pending_tool_results: List[Dict[str, Any]] = []
        i = 0

        while i < len(messages):
            msg = messages[i]
            role = msg.get("role")

            if role == "system":
                content = msg.get("content") or ""
                system_parts.append(str(content))
                i += 1
                continue

            if role == "assistant":
                blocks: List[Dict[str, Any]] = []
                content = msg.get("content")
                if content:
                    blocks.append({"type": "text", "text": str(content)})

                # Convert OpenAI-style tool_calls to Anthropic tool_use blocks
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function", {})
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id") or fn.get("name"),
                            "name": fn.get("name"),
                            "input": json.loads(fn.get("arguments") or "{}")
                            if isinstance(fn.get("arguments"), str)
                            else fn.get("arguments") or {},
                        }
                    )
                add_msg("assistant", blocks)

                # Immediately collect all following tool results
                i += 1
                tool_results = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tool_msg = messages[i]
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_msg.get("tool_call_id"),
                            "content": tool_msg.get("content", ""),
                        }
                    )
                    i += 1

                # Add tool results as a user message if we found any
                if tool_results:
                    add_msg("user", tool_results)
                continue

            if role == "tool":
                # This should be handled in the assistant block above, but handle orphans
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id"),
                        "content": msg.get("content", ""),
                    }
                )
                i += 1
                continue

            if role == "user":
                # Flush any pending orphaned tool results first
                if pending_tool_results:
                    add_msg("user", pending_tool_results)
                    pending_tool_results = []
                content = msg.get("content") or ""
                add_msg("user", [{"type": "text", "text": str(content)}])
                i += 1
                continue

            # Skip unknown roles
            i += 1

        # Flush any remaining tool results at end
        if pending_tool_results:
            add_msg("user", pending_tool_results)

        # Ensure message sequence ends properly for Anthropic
        # Anthropic requires that if the last assistant message has tool_use blocks,
        # there must be a following user message with tool_result blocks
        if anth_messages:
            last_msg = anth_messages[-1]
            if last_msg["role"] == "assistant":
                # Check if the last assistant message has tool_use blocks
                tool_use_blocks = [
                    block for block in last_msg["content"] if block.get("type") == "tool_use"
                ]
                if tool_use_blocks:
                    logger.warning(
                        f"Last assistant message has {len(tool_use_blocks)} tool_use blocks without following tool_results"
                    )
                    # Add synthetic tool_result for all tool_use blocks
                    synthetic_results = []
                    for block in tool_use_blocks:
                        synthetic_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.get("id"),
                                "content": '{"error": "Tool execution in progress", "status": "pending"}',
                            }
                        )
                    if synthetic_results:
                        add_msg("user", synthetic_results)
                        logger.info(
                            f"Added {len(synthetic_results)} synthetic tool_result blocks to satisfy Anthropic requirements"
                        )

        system_text = "\n".join([p for p in system_parts if p]) or None
        return system_text, anth_messages

    async def chat_completion(
        self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None
    ) -> ChatResponse:
        system_text, anth_messages = self._convert_messages(messages)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": anth_messages,
            "max_tokens": 4000,  # Required parameter for Anthropic API
        }
        if system_text:
            payload["system"] = system_text
        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools

        base_url = self.base_url or "https://api.anthropic.com"
        url = f"{base_url}/v1/messages" if not base_url.endswith("/v1") else f"{base_url}/messages"
        logger.debug(f"Sending Anthropic messages request to {url}")

        # Retry with backoff
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                session = await get_session()
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        blocks = data.get("content", [])
                        text_parts: List[str] = []
                        tool_calls: List[Dict[str, Any]] = []
                        for b in blocks:
                            if b.get("type") == "text":
                                text_parts.append(b.get("text", ""))
                            elif b.get("type") == "tool_use":
                                # Convert back to OpenAI-style tool_calls for agent
                                tool_calls.append(
                                    {
                                        "id": b.get("id"),
                                        "type": "function",
                                        "function": {
                                            "name": b.get("name"),
                                            "arguments": json.dumps(b.get("input") or {}),
                                        },
                                    }
                                )

                        content = "\n".join([p for p in text_parts if p])
                        usage = data.get("usage", {})
                        return ChatResponse(content=content, tool_calls=tool_calls, usage=usage)

                    elif response.status >= 500:
                        error_text = await response.text()
                        if attempt < max_retries:
                            delay = base_delay * (2**attempt)
                            logger.warning(
                                f"Anthropic server error {response.status}, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1})"
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise Exception(
                                f"Anthropic server error {response.status}: {error_text}"
                            )

                    else:
                        error_text = await response.text()
                        logger.error(f"Anthropic API error {response.status}: {error_text}")
                        raise Exception(f"Anthropic API error {response.status}: {error_text}")

            except aiohttp.ClientError as e:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Network error in Anthropic request, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"HTTP error in Anthropic request after all retries: {e}")
                    raise Exception(f"Network error: {str(e)}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in Anthropic response: {e}")
                raise Exception(f"Invalid JSON response: {str(e)}")
            except Exception as e:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Unexpected error in Anthropic request, retrying in {delay}s... (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Unexpected error in Anthropic request after all retries: {e}")
                    raise

        raise Exception("Maximum retries exceeded for Anthropic request")


def create_llm_provider() -> LLMProvider:
    """Factory to create the configured LLM provider from Settings."""
    provider = Settings.LLM_PROVIDER

    # Try external provider plugins first (entry points)
    try:
        eps = entry_points(group="sam.llm_providers")  # type: ignore[arg-type]
        for ep in eps:
            if ep.name == provider:
                try:
                    factory = ep.load()
                    try:
                        inst = factory(Settings)  # prefer settings-aware factories
                    except TypeError:
                        inst = factory()
                    if isinstance(inst, LLMProvider):
                        logger.info(f"Loaded external LLM provider via plugin: {provider}")
                        return inst
                except Exception as e:
                    logger.warning(f"Failed to load LLM provider plugin '{provider}': {e}")
                    break
    except Exception:
        # Safe to ignore if no entry points available
        pass

    if provider == "openai":
        return OpenAICompatibleProvider(
            api_key=Settings.OPENAI_API_KEY,
            model=Settings.OPENAI_MODEL,
            base_url=Settings.OPENAI_BASE_URL or "https://api.openai.com/v1",
        )

    if provider == "xai":
        # xAI Grok with custom handling for tool schemas
        return XAIProvider(
            api_key=Settings.XAI_API_KEY or "",
            model=Settings.XAI_MODEL,
            base_url=Settings.XAI_BASE_URL,
        )

    if provider in ("openai_compat", "local"):
        # Generic OpenAI-compatible server (e.g., Ollama/LM Studio/vLLM)
        base_url = (
            Settings.OPENAI_BASE_URL if provider == "openai_compat" else Settings.LOCAL_LLM_BASE_URL
        )
        api_key = (
            Settings.OPENAI_API_KEY
            if provider == "openai_compat"
            else (Settings.LOCAL_LLM_API_KEY or "")
        )
        model = Settings.OPENAI_MODEL if provider == "openai_compat" else Settings.LOCAL_LLM_MODEL
        return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=base_url)

    if provider == "anthropic":
        return AnthropicProvider(
            api_key=Settings.ANTHROPIC_API_KEY or "",
            model=Settings.ANTHROPIC_MODEL,
            base_url=Settings.ANTHROPIC_BASE_URL,
        )

    # Fallback
    logger.warning(
        f"Unknown LLM_PROVIDER '{provider}', defaulting to OpenAI-compatible with OPENAI settings"
    )
    return OpenAICompatibleProvider(
        api_key=Settings.OPENAI_API_KEY,
        model=Settings.OPENAI_MODEL,
        base_url=Settings.OPENAI_BASE_URL or "https://api.openai.com/v1",
    )
