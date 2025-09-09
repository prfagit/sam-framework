from typing import Any, Awaitable, Callable, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError
from dataclasses import dataclass, field
from .middleware import Middleware, ToolContext, ToolCall


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON schema compatible
    namespace: Optional[str] = None  # Optional logical grouping
    version: Optional[str] = None  # Optional tool version for discovery


Handler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class Tool:
    def __init__(
        self,
        spec: ToolSpec,
        handler: Handler,
        *,
        input_model: Optional[Type[BaseModel]] = None,
    ) -> None:
        """A tool with schema and optional Pydantic input validation.

        input_model is optional and non-breaking. If provided, ToolRegistry
        will validate args using the model before invoking the handler,
        passing the validated dict to the handler.
        """
        self.spec = spec
        self.handler = handler
        self.input_model = input_model


class ToolRegistry:
    def __init__(self, middlewares: Optional[List[Middleware]] = None):
        self._tools: Dict[str, Tool] = {}
        self._middlewares: List[Middleware] = list(middlewares or [])

    def register(self, tool: Tool):
        self._tools[tool.spec.name] = tool

    def add_middleware(self, mw: Middleware) -> None:
        self._middlewares.append(mw)

    async def call(
        self, name: str, args: Dict[str, Any], context: Optional[ToolContext] = None
    ) -> Dict[str, Any]:
        """Call a registered tool by name with the given arguments and context."""
        if name not in self._tools:
            # Normalized error shape (non-breaking: keep top-level 'error')
            return {
                "success": False,
                "error": f"Tool '{name}' not found",
                "error_detail": {"code": "not_found", "message": f"Tool '{name}' not found"},
            }
        tool = self._tools[name]

        # Validate using optional input model
        validated_args = args
        if tool.input_model is not None:
            try:
                model = tool.input_model(**(args or {}))
                # Convert to plain dict for handler consumption
                validated_args = model.model_dump()
            except ValidationError as ve:
                # Keep error shape consistent and non-breaking
                return {"error": f"Validation failed: {ve.errors()}"}

        # Build middleware execution chain
        async def base_call(
            call_args: Dict[str, Any], _ctx: Optional[ToolContext]
        ) -> Dict[str, Any]:
            return await tool.handler(call_args)

        call_chain: ToolCall = base_call
        for mw in reversed(self._middlewares):
            call_chain = mw.wrap(name, call_chain)

        try:
            result = await call_chain(validated_args, context)
        except Exception as e:
            # Execution error normalization
            return {
                "success": False,
                "error": f"Tool execution failed: {str(e)}",
                "error_detail": {
                    "code": "execution_error",
                    "message": f"Tool execution failed: {str(e)}",
                },
            }

        # Normalize result shapes while preserving backward compatibility.
        # - Always include 'success': bool
        # - On failures, include 'error_detail': {code, message, details?}
        # - Preserve existing fields (incl. 'error' or data keys) to avoid breaking callers/tests.
        try:
            if isinstance(result, dict):
                # Determine if this is an error result
                if "error" in result:
                    # Two styles supported today: structured (error: True) and simple string error
                    if isinstance(result.get("error"), bool) and result.get("error"):
                        code = str(result.get("category", "error"))
                        message = (
                            str(result.get("message"))
                            if result.get("message") is not None
                            else str(result.get("title", "Error"))
                        )
                    else:
                        code = "error"
                        message = str(result.get("error", "Unknown error"))

                    # Non-breaking: keep original result keys and add normalized flags
                    normalized = dict(result)
                    normalized["success"] = False
                    normalized.setdefault("error_detail", {"code": code, "message": message})
                    return normalized
                else:
                    # Success path: add success flag; keep everything else as-is.
                    normalized = dict(result)
                    normalized["success"] = True
                    return normalized
            else:
                # Non-dict results: wrap minimally
                return {"success": True, "result": result}
        except Exception as e:
            # Fallback if normalization itself fails
            return {
                "success": False,
                "error": f"Normalization failed: {str(e)}",
                "error_detail": {"code": "normalization_error", "message": str(e)},
            }

    def _derive_parameters_from_model(self, model_cls: Type[BaseModel]) -> Dict[str, Any]:
        """Derive JSON schema parameters for OpenAI tool format from a Pydantic model."""
        try:
            schema = model_cls.model_json_schema()
            props = schema.get("properties", {}) or {}
            required = schema.get("required", []) or []
            return {"type": "object", "properties": props, "required": required}
        except Exception:
            # Fallback minimal object shape
            return {"type": "object", "properties": {}, "required": []}

    def list_specs(self) -> List[Dict[str, Any]]:
        # Emit tool specs; if input_model is provided and schema lacks parameters,
        # derive parameters to reduce duplication and keep providers happy.
        specs: List[Dict[str, Any]] = []
        for t in self._tools.values():
            spec = t.spec.model_dump()
            try:
                if t.input_model is not None:
                    input_schema = spec.get("input_schema")
                    derived = self._derive_parameters_from_model(t.input_model)

                    if isinstance(input_schema, dict):
                        if "parameters" in input_schema:
                            params = input_schema.get("parameters")
                            if not params:
                                input_schema["parameters"] = derived
                        elif not ("type" in input_schema and "properties" in input_schema):
                            # Unknown shape: wrap derived under parameters to match OpenAI tool format
                            spec["input_schema"] = {"parameters": derived}
                        # else: already a root JSON schema with type/properties; leave as-is
                    else:
                        # Not a dict or missing: provide derived parameters wrapper
                        spec["input_schema"] = {"parameters": derived}
            except Exception:
                pass
            specs.append(spec)
        return specs


@dataclass
class ToolResult:
    """Typed wrapper for normalized tool results.

    This is optional helper for developers. The framework continues to
    pass dictionaries externally for backward compatibility.
    """

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_detail: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        out = dict(self.data)
        out["success"] = self.success
        if self.error is not None:
            out["error"] = self.error
        if self.error_detail is not None:
            out["error_detail"] = self.error_detail
        return out

    @staticmethod
    def from_raw(raw: Dict[str, Any]) -> "ToolResult":
        if isinstance(raw, dict) and raw.get("error"):
            return ToolResult(
                success=False,
                data={
                    k: v for k, v in raw.items() if k not in {"error", "error_detail", "success"}
                },
                error=str(raw.get("error")),
                error_detail=raw.get("error_detail"),
            )
        return ToolResult(success=True, data=dict(raw or {}))
