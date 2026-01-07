"""Session management endpoints."""

from __future__ import annotations

import asyncio
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from ...config.settings import Settings
from ...core.memory import MemoryManager
from ...core.memory_provider import create_memory_manager
from ...core.quotas import get_quota_manager
from ...utils.sanitize import sanitize_messages, sanitize_session_name
from ..dependencies import get_request_context
from ..schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionListItem,
    SessionUpdateRequest,
)
from ..utils import generate_session_id

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

_MEMORY_MANAGER: MemoryManager = create_memory_manager(Settings.SAM_DB_PATH)
_MEMORY_INITIALIZED = False
_MEMORY_LOCK = asyncio.Lock()


async def _get_memory() -> MemoryManager:
    global _MEMORY_INITIALIZED
    if not _MEMORY_INITIALIZED:
        async with _MEMORY_LOCK:
            if not _MEMORY_INITIALIZED:
                await _MEMORY_MANAGER.initialize()
                _MEMORY_INITIALIZED = True
    return _MEMORY_MANAGER


@router.get("", response_model=List[SessionListItem])
async def list_sessions(
    limit: int = 20,
    context=Depends(get_request_context),
) -> List[SessionListItem]:
    memory = await _get_memory()
    entries = await memory.list_sessions(limit=limit, user_id=context.user_id)
    items: List[SessionListItem] = []
    for entry in entries:
        items.append(
            SessionListItem(
                session_id=entry.get("session_id", ""),
                agent_name=entry.get("agent_name"),
                session_name=entry.get("session_name"),
                created_at=entry.get("created_at"),
                updated_at=entry.get("updated_at"),
                message_count=int(entry.get("message_count", 0)),
                last_message=entry.get("last_message"),
            )
        )
    return items


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    context=Depends(get_request_context),
) -> SessionDetailResponse:
    memory = await _get_memory()
    messages, agent_name, session_name = await memory.load_session(
        session_id, user_id=context.user_id
    )
    return SessionDetailResponse(
        session_id=session_id,
        messages=messages,
        agent_name=agent_name,
        session_name=session_name,
    )


@router.post("", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest,
    context=Depends(get_request_context),
) -> SessionCreateResponse:
    # Check session quota
    quota_manager = get_quota_manager(Settings.SAM_DB_PATH)
    allowed, error_msg = await quota_manager.check_session_quota(context.user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_msg or "Session quota exceeded",
        )

    memory = await _get_memory()
    session_id = payload.session_id or generate_session_id()

    # Sanitize input
    initial_messages = sanitize_messages(payload.messages or [])
    agent_name = payload.agent_name  # Agent names are validated elsewhere
    session_name = sanitize_session_name(payload.session_name) if payload.session_name else None
    await memory.create_session(
        session_id,
        initial_messages=initial_messages,
        user_id=context.user_id,
        agent_name=agent_name,
        session_name=session_name,
    )
    if initial_messages:
        await memory.save_session(
            session_id,
            initial_messages,
            user_id=context.user_id,
            agent_name=agent_name,
            session_name=session_name,
        )
    elif agent_name or session_name:
        # Save agent_name/session_name even if no initial messages
        await memory.save_session(
            session_id,
            [],
            user_id=context.user_id,
            agent_name=agent_name,
            session_name=session_name,
        )
    return SessionCreateResponse(session_id=session_id)


@router.patch("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_session(
    session_id: str,
    payload: SessionUpdateRequest,
    context=Depends(get_request_context),
) -> None:
    memory = await _get_memory()

    # Sanitize session name
    sanitized_name = sanitize_session_name(payload.session_name) if payload.session_name else None

    success = await memory.update_session_name(
        session_id,
        sanitized_name,
        user_id=context.user_id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    context=Depends(get_request_context),
) -> None:
    memory = await _get_memory()
    deleted = await memory.clear_session(session_id, user_id=context.user_id)
    if deleted <= 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


__all__ = ["router"]
