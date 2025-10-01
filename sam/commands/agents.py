"""Agent management commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..agents.definition import AgentDefinition
from ..agents.manager import (
    ensure_agents_dir,
    find_agent_definition,
    list_agent_definitions,
)
from ..config.prompts import SOLANA_AGENT_PROMPT
from ..config.settings import Settings
from ..core.agent_factory import AgentFactory
from ..core.builder import AgentBuilder
from ..core.context import RequestContext
from ..utils.cli_helpers import CLIFormatter


def _resolve_agent_file(name: str) -> Path:
    directory = ensure_agents_dir()
    return directory / f"{name}.agent.toml"


def list_agents_command() -> int:
    definitions = sorted(list_agent_definitions(), key=lambda d: d.name.lower())
    if not definitions:
        print(
            CLIFormatter.info(
                "No agent definitions found. Use `sam agent init <name>` to create one."
            )
        )
        return 0

    print(CLIFormatter.header("Available Agents"))

    for idx, definition in enumerate(definitions, 1):
        bullet = CLIFormatter.colorize(f"{idx:>2}.", CLIFormatter.DIM)
        name = CLIFormatter.colorize(definition.name, CLIFormatter.BOLD + CLIFormatter.GREEN)
        description = definition.description or "No description provided"
        description_colored = CLIFormatter.colorize(description, CLIFormatter.DIM)

        tool_list = sorted(definition.enabled_tools.keys())
        if tool_list:
            tools_colored = CLIFormatter.colorize(", ".join(tool_list), CLIFormatter.CYAN)
        else:
            tools_colored = CLIFormatter.colorize("(default tools)", CLIFormatter.DIM)

        if definition.path:
            try:
                path_display = definition.path.resolve().relative_to(Path.cwd())
            except ValueError:
                path_display = definition.path.resolve()
        else:
            path_display = Path("<unknown>")
        path_colored = CLIFormatter.colorize(str(path_display), CLIFormatter.YELLOW)

        tags_colored = ""
        if definition.metadata and definition.metadata.tags:
            tags = " ".join(f"#{tag}" for tag in definition.metadata.tags)
            tags_colored = CLIFormatter.colorize(tags, CLIFormatter.MAGENTA)

        print(f"{bullet} {name}")
        print(f"   {description_colored}")
        print(f"   {CLIFormatter.colorize('Tools:', CLIFormatter.BLUE)} {tools_colored}")
        if tags_colored:
            print(f"   {CLIFormatter.colorize('Tags:', CLIFormatter.BLUE)} {tags_colored}")
        print(f"   {CLIFormatter.colorize('File:', CLIFormatter.BLUE)} {path_colored}\n")
    return 0


def init_agent_command(name: str, *, overwrite: bool = False) -> int:
    ensure_agents_dir()
    file_path = _resolve_agent_file(name)
    if file_path.exists() and not overwrite:
        print(CLIFormatter.error(f"Agent definition {file_path} already exists."))
        return 1

    prompt = SOLANA_AGENT_PROMPT.strip()

    llm_lines = [f'provider = "{Settings.LLM_PROVIDER}"']
    if Settings.LLM_PROVIDER == "openai" and Settings.OPENAI_MODEL:
        llm_lines.append(f'model = "{Settings.OPENAI_MODEL}"')
    llm_section = "[llm]\n" + "\n".join(llm_lines) + "\n\n"

    author = os.getenv("USER", "you")

    template = (
        f'name = "{name}"\n'
        'description = "Your custom SAM agent"\n'
        f"system_prompt = '''{prompt}'''\n\n"
        f"{llm_section}"
        '[[tools]]\nname = "solana"\nenabled = true\n\n'
        '[[tools]]\nname = "jupiter"\nenabled = true\n\n'
        "[metadata]\n"
        f'author = "{author}"\n'
        'version = "0.1.0"\n'
        'tags = ["example"]\n'
    )

    file_path.write_text(template, encoding="utf-8")
    print(CLIFormatter.success(f"Created agent definition at {file_path}"))
    return 0


def load_agent_definition(name: str) -> Optional[AgentDefinition]:
    definition = find_agent_definition(name)
    if not definition:
        print(CLIFormatter.error(f"Could not find agent definition '{name}'."))
        return None
    return definition


async def run_agent_definition(
    definition: AgentDefinition,
    *,
    session_id: str,
    no_animation: bool = False,
    clear_sessions: bool = False,
) -> int:
    from ..cli import run_interactive_session

    tool_overrides: Optional[dict[str, bool]] = None
    if definition.tools:
        tool_overrides = {bundle: False for bundle in AgentBuilder.KNOWN_TOOL_BUNDLES}
        for tool in definition.tools:
            tool_name = tool.name.strip().lower()
            if tool_name:
                tool_overrides[tool_name] = tool.enabled

    llm_config = definition.llm.model_dump(exclude_none=True) if definition.llm else None

    builder = AgentBuilder(
        system_prompt=definition.system_prompt,
        llm_config=llm_config,
        tool_overrides=tool_overrides,
    )
    factory = AgentFactory(builder=builder)

    resolved_session = session_id
    if not resolved_session or resolved_session in {"default", ""}:
        resolved_session = definition.name

    return await run_interactive_session(
        resolved_session,
        no_animation,
        clear_sessions=clear_sessions,
        factory=factory,
        agent_context=RequestContext(user_id=f"agent:{definition.name}"),
        agent_name=definition.name,
        agent_description=definition.description,
        agent_tags=definition.metadata.tags,
    )
