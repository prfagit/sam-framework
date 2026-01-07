"""Agent management endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from ...agents.definition import AgentDefinition
from ...agents.manager import find_agent_definition, list_agent_definitions
from ...core.builder import AgentBuilder, cleanup_agent_fast
from ...core.context import RequestContext
from ...core.quotas import get_quota_manager
from ...config.settings import Settings
from ..dependencies import APIUser, get_current_user, get_request_context
from ..public_storage import get_public_storage
from ..schemas import (
    AgentCreateResponse,
    AgentDetailResponse,
    AgentListItem,
    AgentSource,
    AgentVisibility,
    RunRequest,
    RunResponse,
)
from ..storage import (
    delete_user_definition_async,
    list_user_definitions_async,
    load_user_definition_async,
    save_user_definition_async,
)
from ..utils import generate_session_id, sanitize_agent_name

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/agents", tags=["agents"])

_EVENT_NAMES: tuple[str, ...] = (
    "agent.status",
    "agent.delta",
    "agent.message",
    "llm.usage",
    "tool.called",
    "tool.failed",
    "tool.succeeded",
)

_FINAL_EVENT = "agent.final"


def _path_timestamp(path: object | None) -> str | None:
    candidate: Path | None
    if isinstance(path, Path):
        candidate = path
    elif isinstance(path, (str, bytes)):
        candidate = Path(path)
    else:
        candidate = None

    if not candidate or not candidate.exists():
        return None
    mtime = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
    return mtime.isoformat()


def _definition_to_list_item(definition: AgentDefinition, source: AgentSource) -> AgentListItem:
    tags = definition.metadata.tags if definition.metadata else []
    return AgentListItem(
        name=definition.name,
        description=definition.description or "",
        tags=tags,
        source=source,
        updated_at=_path_timestamp(definition.path),
    )


def _create_builder(definition: AgentDefinition) -> AgentBuilder:
    tool_overrides = None
    if definition.tools:
        tool_overrides = {bundle: False for bundle in AgentBuilder.KNOWN_TOOL_BUNDLES}
        for tool in definition.tools:
            name = tool.name.strip().lower()
            if name:
                tool_overrides[name] = tool.enabled

    llm_config = definition.llm.model_dump(exclude_none=True) if definition.llm else None

    return AgentBuilder(
        system_prompt=definition.system_prompt,
        llm_config=llm_config,
        tool_overrides=tool_overrides,
    )


def _serialize_usage(stats: Dict[str, object]) -> Dict[str, int]:
    usage: Dict[str, int] = {}
    for key, value in stats.items():
        if isinstance(value, (int, float)):
            usage[key] = int(value)
    return usage


def _copy_definition(definition: AgentDefinition) -> AgentDefinition:
    data = definition.model_dump(exclude={"path"}, exclude_none=True)
    return AgentDefinition.from_dict(data)


def _format_sse_event(event: str, payload: Dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def _resolve_definition(name: str, user_id: str) -> tuple[AgentDefinition, AgentSource]:
    definition = await load_user_definition_async(user_id, name)
    if definition:
        return definition, AgentSource.USER
    fallback = find_agent_definition(name)
    if fallback:
        return fallback, AgentSource.BUILTIN
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")


@router.get("", response_model=List[AgentListItem])
async def list_agents(
    include_templates: bool = True,
    user: APIUser = Depends(get_current_user),
) -> List[AgentListItem]:
    items: List[AgentListItem] = []
    seen: set[str] = set()
    storage = get_public_storage(Settings.SAM_DB_PATH)

    for definition in await list_user_definitions_async(user.user_id):
        item = _definition_to_list_item(definition, AgentSource.USER)

        # Look up public status for user's agents
        public_entry = await storage.get_for_agent(user.user_id, definition.name)
        if public_entry:
            item.visibility = AgentVisibility(public_entry.visibility)
            item.public_id = public_entry.public_id

        items.append(item)
        seen.add(definition.name.lower())

    if include_templates:
        for definition in list_agent_definitions():
            key = definition.name.lower()
            if key in seen:
                continue
            items.append(_definition_to_list_item(definition, AgentSource.BUILTIN))

    items.sort(key=lambda item: item.name.lower())
    return items


@router.get("/{name}", response_model=AgentDetailResponse)
async def get_agent_definition(
    name: str,
    user: APIUser = Depends(get_current_user),
) -> AgentDetailResponse:
    definition, source = await _resolve_definition(name, user.user_id)
    safe_definition = _copy_definition(definition)
    return AgentDetailResponse(source=source, definition=safe_definition)


@router.post("", response_model=AgentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_definition(
    definition: AgentDefinition,
    user: APIUser = Depends(get_current_user),
) -> AgentCreateResponse:
    # Check agent quota
    quota_manager = get_quota_manager(Settings.SAM_DB_PATH)
    allowed, error_msg = await quota_manager.check_agent_quota(user.user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_msg or "Agent quota exceeded",
        )

    existing = await load_user_definition_async(user.user_id, definition.name)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent already exists")

    path = await save_user_definition_async(user.user_id, definition)
    logger.info("Created agent '%s' for user %s", definition.name, user.user_id)
    return AgentCreateResponse(name=definition.name, source=AgentSource.USER, path=str(path))


@router.put("/{name}", response_model=AgentCreateResponse)
async def update_agent_definition(
    name: str,
    definition: AgentDefinition,
    user: APIUser = Depends(get_current_user),
) -> AgentCreateResponse:
    if sanitize_agent_name(name) != sanitize_agent_name(definition.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent name in path and payload must match",
        )

    path = await save_user_definition_async(user.user_id, definition)
    logger.info("Updated agent '%s' for user %s", definition.name, user.user_id)
    return AgentCreateResponse(name=definition.name, source=AgentSource.USER, path=str(path))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_definition_endpoint(
    name: str,
    user: APIUser = Depends(get_current_user),
) -> None:
    deleted = await delete_user_definition_async(user.user_id, name)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # Also clean up any public agent entries
    storage = get_public_storage(Settings.SAM_DB_PATH)
    await storage.delete_public_entry(user.user_id, name)

    logger.info("Deleted agent '%s' for user %s", name, user.user_id)


async def _execute_agent_run(
    agent: AgentDefinition,
    prompt: str,
    session_id: str,
    context: RequestContext,
    agent_name: Optional[str] = None,
) -> RunResponse:
    builder = _create_builder(agent)
    sam_agent = await builder.build(context=context)

    events: List[Dict[str, object]] = []

    async def handler(event: str, payload: Dict[str, object]) -> None:
        if payload.get("session_id") == session_id and payload.get("user_id") == context.user_id:
            events.append({"event": event, "payload": payload})

    for event_name in _EVENT_NAMES:
        sam_agent.events.subscribe(event_name, handler)

    try:
        await sam_agent.memory.create_session(
            session_id, user_id=context.user_id, agent_name=agent_name
        )
        response_text = await sam_agent.run(prompt, session_id, context=context)
        await asyncio.sleep(0)
        usage = _serialize_usage(sam_agent.session_stats)

        # Track token usage in quota
        total_tokens = usage.get("total_tokens", 0)
        if total_tokens > 0:
            quota_manager = get_quota_manager(Settings.SAM_DB_PATH)
            allowed, error_msg = await quota_manager.check_token_quota(
                context.user_id, total_tokens
            )
            if not allowed:
                logger.warning(
                    f"Token quota exceeded for user {context.user_id} after run: {error_msg}"
                )
                # Don't fail the request, but log the warning

        return RunResponse(
            session_id=session_id, response=response_text or "", usage=usage, events=events
        )
    finally:
        for event_name in _EVENT_NAMES:
            sam_agent.events.unsubscribe(event_name, handler)
        try:
            await sam_agent.close()
        finally:
            await cleanup_agent_fast()


@router.post("/{name}/runs", response_model=RunResponse)
async def run_agent_endpoint(
    name: str,
    request: RunRequest,
    context: RequestContext = Depends(get_request_context),
) -> RunResponse:
    definition, _ = await _resolve_definition(name, context.user_id)
    session_id = request.session_id or generate_session_id(name)

    try:
        return await _execute_agent_run(
            definition, request.prompt, session_id, context, agent_name=name
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Agent run failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent execution failed",
        )


async def _stream_agent_run(
    agent: AgentDefinition,
    prompt: str,
    session_id: str,
    context: RequestContext,
    agent_name: Optional[str] = None,
) -> StreamingResponse:
    builder = _create_builder(agent)
    sam_agent = await builder.build(context=context)

    queue: asyncio.Queue[Optional[Dict[str, object]]] = asyncio.Queue()
    done = asyncio.Event()

    async def handler(event: str, payload: Dict[str, object]) -> None:
        if payload.get("session_id") == session_id and payload.get("user_id") == context.user_id:
            await queue.put({"event": event, "payload": payload})

    for event_name in _EVENT_NAMES:
        sam_agent.events.subscribe(event_name, handler)

    async def runner() -> None:
        try:
            await sam_agent.memory.create_session(
                session_id, user_id=context.user_id, agent_name=agent_name
            )
            reply = await sam_agent.run(prompt, session_id, context=context)
            usage = _serialize_usage(sam_agent.session_stats)

            # Track token usage in quota
            total_tokens = usage.get("total_tokens", 0)
            if total_tokens > 0:
                quota_manager = get_quota_manager(Settings.SAM_DB_PATH)
                allowed, error_msg = await quota_manager.check_token_quota(
                    context.user_id, total_tokens
                )
                if not allowed:
                    logger.warning(
                        f"Token quota exceeded for user {context.user_id} after stream: {error_msg}"
                    )
                    # Don't fail the request, but log the warning

            await queue.put(
                {
                    "event": _FINAL_EVENT,
                    "payload": {
                        "session_id": session_id,
                        "user_id": context.user_id,
                        "response": reply or "",
                        "usage": usage,
                    },
                }
            )
        except Exception as exc:
            await queue.put(
                {
                    "event": "agent.error",
                    "payload": {
                        "session_id": session_id,
                        "user_id": context.user_id,
                        "error": str(exc),
                    },
                }
            )
            logger.exception("Streaming agent run failed: %s", exc)
        finally:
            for event_name in _EVENT_NAMES:
                sam_agent.events.unsubscribe(event_name, handler)
            try:
                await sam_agent.close()
            finally:
                await cleanup_agent_fast()
                await queue.put(None)
                done.set()

    task = asyncio.create_task(runner())

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event = _format_sse_event(item["event"], item["payload"])
                yield event.encode("utf-8")
        finally:
            if not done.is_set():
                task.cancel()
                with contextlib.suppress(Exception):
                    await task

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{name}/stream")
async def stream_agent_endpoint(
    name: str,
    request: RunRequest,
    context: RequestContext = Depends(get_request_context),
) -> StreamingResponse:
    definition, _ = await _resolve_definition(name, context.user_id)
    session_id = request.session_id or generate_session_id(name)
    return await _stream_agent_run(definition, request.prompt, session_id, context, agent_name=name)


__all__ = ["router"]
