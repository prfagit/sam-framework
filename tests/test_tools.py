import pytest
from sam.core.tools import Tool, ToolSpec, ToolRegistry


@pytest.mark.asyncio
async def test_tool_registry():
    """Test tool registration and execution."""
    registry = ToolRegistry()

    # Create a test tool
    async def test_handler(args):
        return {"result": f"processed {args.get('input', 'nothing')}"}

    tool_spec = ToolSpec(
        name="test_tool",
        description="A test tool",
        input_schema={
            "name": "test_tool",
            "description": "Test tool",
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
        },
    )

    tool = Tool(spec=tool_spec, handler=test_handler)

    # Register tool
    registry.register(tool)

    # Test tool listing
    specs = registry.list_specs()
    assert len(specs) == 1
    assert specs[0]["name"] == "test_tool"

    # Test tool execution
    result = await registry.call("test_tool", {"input": "hello"})
    assert result["result"] == "processed hello"


@pytest.mark.asyncio
async def test_tool_error_handling():
    """Test tool error handling."""
    registry = ToolRegistry()

    # Create a tool that raises an exception
    async def error_handler(args):
        raise ValueError("Test error")

    tool_spec = ToolSpec(
        name="error_tool",
        description="A tool that errors",
        input_schema={
            "name": "error_tool",
            "description": "Error tool",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    )

    tool = Tool(spec=tool_spec, handler=error_handler)
    registry.register(tool)

    # Test error handling
    result = await registry.call("error_tool", {})
    assert "error" in result
    assert "Test error" in result["error"]


@pytest.mark.asyncio
async def test_nonexistent_tool():
    """Test calling a tool that doesn't exist."""
    registry = ToolRegistry()

    result = await registry.call("nonexistent_tool", {})
    assert "error" in result
    assert "not found" in result["error"]


def test_tool_spec_serialization():
    """Test that tool specs can be serialized properly."""
    tool_spec = ToolSpec(
        name="test_tool",
        description="A test tool",
        input_schema={
            "name": "test_tool",
            "description": "Test",
            "parameters": {"type": "object", "properties": {"param1": {"type": "string"}}},
        },
    )

    # Should be able to convert to dict (for JSON serialization)
    spec_dict = tool_spec.model_dump()
    assert spec_dict["name"] == "test_tool"
    assert "input_schema" in spec_dict
