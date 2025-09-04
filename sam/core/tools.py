from typing import Any, Awaitable, Callable, Dict, List
from pydantic import BaseModel


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON schema compatible


Handler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


class Tool:
    def __init__(self, spec: ToolSpec, handler: Handler):
        self.spec = spec
        self.handler = handler


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool):
        self._tools[tool.spec.name] = tool
    
    def list_specs(self) -> List[Dict[str, Any]]:
        return [t.spec.model_dump() for t in self._tools.values()]
    
    async def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"error": f"Tool '{name}' not found"}
        try:
            return await self._tools[name].handler(args)
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}