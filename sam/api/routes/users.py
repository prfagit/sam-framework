"""User management and quota endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config.settings import Settings
from ...core.quotas import get_quota_manager
from ..dependencies import APIUser, get_current_user
from ..schemas import QuotaStatusResponse, QuotaUsage, TokenQuotaUsage

router = APIRouter(prefix="/v1/users", tags=["users"])


@router.get("/me/quota", response_model=QuotaStatusResponse)
async def get_my_quota(user: APIUser = Depends(get_current_user)) -> QuotaStatusResponse:
    """Get quota status for the current user."""
    quota_manager = get_quota_manager(Settings.SAM_DB_PATH)
    status_data = await quota_manager.get_quota_status(user.user_id)

    # Transform the response to match the schema
    return QuotaStatusResponse(
        user_id=status_data["user_id"],
        sessions=QuotaUsage(**status_data["sessions"]),
        agents=QuotaUsage(**status_data["agents"]),
        tokens=TokenQuotaUsage(
            used_today=status_data["tokens"]["used_today"],
            limit=status_data["tokens"]["limit"],
            remaining=status_data["tokens"]["remaining"],
            resets_at=status_data["tokens"].get("resets_at"),
        ),
        messages_per_session=status_data.get("messages_per_session", {}),
    )
