# Example Plugins

This folder contains a minimal plugin demonstrating how to extend SAM with custom tools.

## Simple Plugin

Module: `examples.plugins.simple_plugin.plugin`

Registers two tools:
- `echo` — echoes back the provided `message`
- `time_now` — returns the current UTC timestamp

### Try it

From the repository root:

```bash
export SAM_PLUGINS="examples.plugins.simple_plugin.plugin"
uv run sam tools
```

You should see `echo` and `time_now` included in the tool list with the `examples` namespace.

To use one in a session, you can simply run the agent and prompt it to call the tool (LLM‑driven), or create a small script that calls `ToolRegistry.call()` directly.

