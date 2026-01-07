"""Public agent and marketplace endpoints."""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...agents.definition import AgentDefinition
from ...config.settings import Settings
from ..dependencies import APIUser, get_current_user, get_current_user_optional
from ..public_storage import get_public_storage, PublicAgentStorage
from ..schemas import (
    AgentRatingResponse,
    AgentRatingsListResponse,
    AgentSource,
    AgentVisibility,
    CloneAgentRequest,
    CloneAgentResponse,
    PublicAgentDetailResponse,
    PublicAgentListItem,
    PublicAgentsListResponse,
    PublishAgentRequest,
    PublishAgentResponse,
    RateAgentRequest,
    ShareAgentResponse,
)
from ..storage import load_user_definition_async, save_user_definition_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agents", tags=["public-agents"])


def _get_storage() -> PublicAgentStorage:
    """Get the public storage instance."""
    return get_public_storage(Settings.SAM_DB_PATH)


# =============================================================================
# Public Agent Marketplace Endpoints
# =============================================================================


@router.get("/public", response_model=PublicAgentsListResponse)
async def list_public_agents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, max_length=100),
    sort: Literal["popular", "recent", "rating"] = Query(default="popular"),
    user: Optional[APIUser] = Depends(get_current_user_optional),
) -> PublicAgentsListResponse:
    """
    List public agents in the marketplace.

    - **limit**: Maximum number of agents to return (1-100)
    - **offset**: Pagination offset
    - **search**: Search query for agent name
    - **sort**: Sort order - 'popular', 'recent', or 'rating'
    """
    storage = _get_storage()

    # Optionally exclude current user's agents from results
    exclude_user = user.user_id if user else None

    entries, total = await storage.list_public_agents(
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
        exclude_user_id=exclude_user,
    )

    # Convert to response items with agent definitions for description/tags
    items: List[PublicAgentListItem] = []
    for entry in entries:
        # Try to load agent definition to get description and tags
        definition = await load_user_definition_async(entry.user_id, entry.agent_name)
        description = ""
        author = None
        tags: List[str] = []

        if definition:
            description = definition.description or ""
            tags = definition.metadata.tags if definition.metadata else []
            author = definition.metadata.author if definition.metadata else None

        items.append(
            PublicAgentListItem(
                public_id=entry.public_id,
                agent_name=entry.agent_name,
                description=description,
                author=author,
                author_id=entry.user_id,
                tags=tags,
                visibility=AgentVisibility(entry.visibility),
                download_count=entry.download_count,
                rating=entry.rating,
                rating_count=entry.rating_count,
                published_at=entry.published_at.isoformat() if entry.published_at else None,
            )
        )

    return PublicAgentsListResponse(
        agents=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/public/{public_id}", response_model=PublicAgentDetailResponse)
async def get_public_agent(
    public_id: str,
    user: Optional[APIUser] = Depends(get_current_user_optional),
) -> PublicAgentDetailResponse:
    """
    Get details of a public agent by its public ID.

    Returns the full agent definition for public or unlisted agents.
    """
    storage = _get_storage()
    entry = await storage.get_by_public_id(public_id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Only allow access to public agents via this endpoint
    if entry.visibility == "private":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Load the actual agent definition
    definition = await load_user_definition_async(entry.user_id, entry.agent_name)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent definition not found",
        )

    # Get current user's rating if logged in
    user_rating = None
    if user:
        rating = await storage.get_user_rating(public_id, user.user_id)
        if rating:
            user_rating = rating.rating

    # Get author name (could be from definition metadata or user lookup)
    author_name = definition.metadata.author if definition.metadata else None

    return PublicAgentDetailResponse(
        public_id=entry.public_id,
        visibility=AgentVisibility(entry.visibility),
        share_token=entry.share_token if entry.visibility == "unlisted" else None,
        download_count=entry.download_count,
        rating=entry.rating,
        rating_count=entry.rating_count,
        published_at=entry.published_at.isoformat() if entry.published_at else None,
        definition=definition,
        author_id=entry.user_id,
        author_name=author_name,
        user_rating=user_rating,
    )


@router.get("/shared/{share_token}", response_model=PublicAgentDetailResponse)
async def get_shared_agent(
    share_token: str,
    user: Optional[APIUser] = Depends(get_current_user_optional),
) -> PublicAgentDetailResponse:
    """
    Access a shared agent via its share token.

    This endpoint allows access to unlisted agents via their share link.
    """
    storage = _get_storage()
    entry = await storage.get_by_share_token(share_token)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared agent not found or link expired",
        )

    # Load the actual agent definition
    definition = await load_user_definition_async(entry.user_id, entry.agent_name)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent definition not found",
        )

    # Get current user's rating if logged in
    user_rating = None
    if user:
        rating = await storage.get_user_rating(entry.public_id, user.user_id)
        if rating:
            user_rating = rating.rating

    author_name = definition.metadata.author if definition.metadata else None

    return PublicAgentDetailResponse(
        public_id=entry.public_id,
        visibility=AgentVisibility(entry.visibility),
        share_token=entry.share_token,
        download_count=entry.download_count,
        rating=entry.rating,
        rating_count=entry.rating_count,
        published_at=entry.published_at.isoformat() if entry.published_at else None,
        definition=definition,
        author_id=entry.user_id,
        author_name=author_name,
        user_rating=user_rating,
    )


# =============================================================================
# Agent Publishing Endpoints (Authenticated)
# =============================================================================


@router.post("/{name}/publish", response_model=PublishAgentResponse)
async def publish_agent(
    name: str,
    request: PublishAgentRequest,
    user: APIUser = Depends(get_current_user),
) -> PublishAgentResponse:
    """
    Publish an agent to the marketplace or generate share link.

    - **visibility**: 'public' for marketplace, 'unlisted' for share link only
    """
    # Verify user owns this agent
    definition = await load_user_definition_async(user.user_id, name)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    storage = _get_storage()

    # Map enum to literal
    visibility_value: Literal["private", "unlisted", "public"] = request.visibility.value  # type: ignore

    entry = await storage.publish_agent(
        user_id=user.user_id,
        agent_name=name,
        visibility=visibility_value,
    )

    logger.info(
        "Agent '%s' published by user %s with visibility '%s'",
        name,
        user.user_id,
        visibility_value,
    )

    return PublishAgentResponse(
        public_id=entry.public_id,
        visibility=AgentVisibility(entry.visibility),
        share_token=entry.share_token,
        published_at=entry.published_at.isoformat() if entry.published_at else None,
    )


@router.post("/{name}/unpublish", status_code=status.HTTP_204_NO_CONTENT)
async def unpublish_agent(
    name: str,
    user: APIUser = Depends(get_current_user),
) -> None:
    """
    Unpublish an agent (set visibility to private).

    The agent will no longer appear in the marketplace or be accessible via share links.
    """
    # Verify user owns this agent
    definition = await load_user_definition_async(user.user_id, name)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    storage = _get_storage()
    success = await storage.unpublish_agent(user.user_id, name)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent was not published",
        )

    logger.info("Agent '%s' unpublished by user %s", name, user.user_id)


@router.post("/{name}/share", response_model=ShareAgentResponse)
async def share_agent(
    name: str,
    user: APIUser = Depends(get_current_user),
) -> ShareAgentResponse:
    """
    Generate a share link for an agent.

    If the agent is not yet published, it will be set to 'unlisted' visibility.
    Returns a unique share URL that can be used to access the agent.
    """
    # Verify user owns this agent
    definition = await load_user_definition_async(user.user_id, name)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    storage = _get_storage()

    # Check if already has a public entry
    entry = await storage.get_for_agent(user.user_id, name)

    if entry and entry.share_token:
        # Already has a share token
        share_url = f"/agents/shared/{entry.share_token}"
    else:
        # Create or update with unlisted visibility to get share token
        entry = await storage.publish_agent(
            user_id=user.user_id,
            agent_name=name,
            visibility="unlisted",
        )
        share_url = f"/agents/shared/{entry.share_token}"

    logger.info("Share link generated for agent '%s' by user %s", name, user.user_id)

    return ShareAgentResponse(
        public_id=entry.public_id,
        share_token=entry.share_token or "",
        share_url=share_url,
    )


# =============================================================================
# Clone Endpoint
# =============================================================================


@router.post("/public/{public_id}/clone", response_model=CloneAgentResponse)
async def clone_public_agent(
    public_id: str,
    request: CloneAgentRequest,
    user: APIUser = Depends(get_current_user),
) -> CloneAgentResponse:
    """
    Clone a public agent to your own collection.

    Creates a copy of the agent definition under your user account.
    """
    storage = _get_storage()
    entry = await storage.get_by_public_id(public_id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Only allow cloning public or unlisted agents
    if entry.visibility == "private":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Prevent cloning your own agent
    if entry.user_id == user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clone your own agent",
        )

    # Load the original definition
    original = await load_user_definition_async(entry.user_id, entry.agent_name)
    if not original:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent definition not found",
        )

    # Determine new name
    if request.new_name:
        new_name = request.new_name.strip()
    else:
        new_name = f"{original.name}-clone"

    # Check if name already exists for user
    existing = await load_user_definition_async(user.user_id, new_name)
    if existing:
        # Add suffix to make unique
        counter = 1
        base_name = new_name
        while await load_user_definition_async(user.user_id, new_name):
            counter += 1
            new_name = f"{base_name}-{counter}"

    # Create cloned definition
    cloned_data = original.model_dump(exclude={"path"}, exclude_none=True)
    cloned_data["name"] = new_name

    # Update metadata to indicate it's a clone
    if "metadata" not in cloned_data:
        cloned_data["metadata"] = {}
    cloned_data["metadata"]["visibility"] = "private"  # Clones start as private
    cloned_data["metadata"]["public_id"] = None
    cloned_data["metadata"]["share_token"] = None
    cloned_data["metadata"]["published_at"] = None
    cloned_data["metadata"]["download_count"] = 0
    cloned_data["metadata"]["rating"] = None
    cloned_data["metadata"]["rating_count"] = 0

    cloned = AgentDefinition.from_dict(cloned_data)

    # Save the cloned agent
    await save_user_definition_async(user.user_id, cloned)

    # Increment download count on original
    await storage.increment_download_count(public_id)

    logger.info(
        "Agent '%s' (public_id=%s) cloned to '%s' by user %s",
        entry.agent_name,
        public_id,
        new_name,
        user.user_id,
    )

    return CloneAgentResponse(
        name=new_name,
        source=AgentSource.USER,
        cloned_from=public_id,
    )


# =============================================================================
# Rating Endpoints
# =============================================================================


@router.post("/public/{public_id}/rate", response_model=AgentRatingResponse)
async def rate_agent(
    public_id: str,
    request: RateAgentRequest,
    user: APIUser = Depends(get_current_user),
) -> AgentRatingResponse:
    """
    Rate a public agent.

    You can only rate an agent once, but you can update your rating.
    """
    storage = _get_storage()
    entry = await storage.get_by_public_id(public_id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Only allow rating public agents
    if entry.visibility != "public":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only rate public agents",
        )

    # Prevent rating your own agent
    if entry.user_id == user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot rate your own agent",
        )

    rating = await storage.add_rating(
        public_id=public_id,
        user_id=user.user_id,
        rating=request.rating,
        comment=request.comment,
    )

    logger.info(
        "Agent '%s' rated %d stars by user %s",
        public_id,
        request.rating,
        user.user_id,
    )

    return AgentRatingResponse(
        user_id=rating.user_id,
        rating=rating.rating,
        comment=rating.comment,
        created_at=rating.created_at.isoformat(),
    )


@router.get("/public/{public_id}/ratings", response_model=AgentRatingsListResponse)
async def get_agent_ratings(
    public_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AgentRatingsListResponse:
    """
    Get ratings for a public agent.
    """
    storage = _get_storage()
    entry = await storage.get_by_public_id(public_id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Only show ratings for public agents
    if entry.visibility != "public":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    ratings, total = await storage.get_agent_ratings(public_id, limit, offset)

    return AgentRatingsListResponse(
        public_id=public_id,
        average_rating=entry.rating,
        rating_count=entry.rating_count,
        ratings=[
            AgentRatingResponse(
                user_id=r.user_id,
                rating=r.rating,
                comment=r.comment,
                created_at=r.created_at.isoformat(),
            )
            for r in ratings
        ],
        total=total,
    )


__all__ = ["router"]
