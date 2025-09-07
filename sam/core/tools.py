from typing import Any, Awaitable, Callable, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON schema compatible


Handler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class Tool:
    def __init__(
        self,
        spec: ToolSpec,
        handler: Handler,
        *,
        input_model: Optional[Type[BaseModel]] = None,
    ):
        """A tool with schema and optional Pydantic input validation.

        input_model is optional and non-breaking. If provided, ToolRegistry
        will validate args using the model before invoking the handler,
        passing the validated dict to the handler.
        """
        self.spec = spec
        self.handler = handler
        self.input_model = input_model


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.spec.name] = tool

    def list_specs(self) -> List[Dict[str, Any]]:
        # For now, always emit the provided spec as-is to avoid surprises.
        # Future: if input_model is provided and spec lacks parameters,
        # we could derive JSON schema from the model.
        return [t.spec.model_dump() for t in self._tools.values()]

    async def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"error": f"Tool '{name}' not found"}
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

        try:
            return await tool.handler(validated_args)
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}
