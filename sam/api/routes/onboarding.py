"""Onboarding endpoints for username and operational wallet setup."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...config.settings import Settings
from ...utils.rate_limiter import check_rate_limit
from ..dependencies import APIUser, get_current_user
from ..schemas import (
    CheckUsernameRequest,
    CheckUsernameResponse,
    CompleteOnboardingRequest,
    CompleteOnboardingResponse,
    OnboardingStatusResponse,
    UserProfileResponse,
)
from ..services.onboarding import OnboardingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])


def _get_service() -> OnboardingService:
    """Get the onboarding service instance."""
    return OnboardingService(Settings.SAM_DB_PATH)


async def _get_client_identifier(request: Request) -> str:
    """Get client identifier for rate limiting."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    user: APIUser = Depends(get_current_user),
) -> OnboardingStatusResponse:
    """Get current user's onboarding status.

    Returns whether onboarding is complete, the user's username (if set),
    and whether they have an operational wallet.
    """
    service = _get_service()
    return await service.get_status(user.user_id)


@router.post("/check-username", response_model=CheckUsernameResponse)
async def check_username_availability(
    data: CheckUsernameRequest,
    request: Request,
    user: APIUser = Depends(get_current_user),
) -> CheckUsernameResponse:
    """Check if a username is available.

    Usernames must be:
    - 3-30 characters long
    - Alphanumeric plus underscore only
    - Unique (case-insensitive)
    """
    # Rate limit username checks to prevent enumeration
    client_id = await _get_client_identifier(request)
    allowed, rate_info = await check_rate_limit(
        identifier=f"onboarding:check-username:{client_id}",
        limit_type="api_general",  # Use general API limits
    )

    if not allowed:
        retry_after = int(rate_info.get("retry_after", 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    service = _get_service()
    available = await service.is_username_available(data.username)
    return CheckUsernameResponse(available=available, username=data.username)


@router.post("/complete", response_model=CompleteOnboardingResponse)
async def complete_onboarding(
    data: CompleteOnboardingRequest,
    user: APIUser = Depends(get_current_user),
) -> CompleteOnboardingResponse:
    """Complete onboarding by setting username and generating operational wallet.

    **IMPORTANT**: The operational wallet's private key is returned ONLY in this response.
    It is never stored in plaintext and will never be returned again.
    The user MUST back up their private key during this step.

    This endpoint can only be called once per user.
    """
    service = _get_service()

    # Check if already onboarded
    current_status = await service.get_status(user.user_id)
    if current_status.onboarding_complete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Onboarding already completed",
        )

    # Validate username availability
    if not await service.is_username_available(data.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    # Complete onboarding (generates wallet, stores encrypted key)
    result = await service.complete_onboarding(
        user_id=user.user_id,
        username=data.username,
    )

    logger.info(
        "Onboarding completed for user %s with username '%s'",
        user.user_id[:8],
        data.username,
    )

    return result


@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(
    user: APIUser = Depends(get_current_user),
) -> UserProfileResponse:
    """Get current user's full profile including onboarding status.

    This includes:
    - User ID and login wallet address
    - Username (if set)
    - Admin status
    - Onboarding completion status
    - Operational wallet public address (if set)
    """
    service = _get_service()
    return await service.get_user_profile(user.user_id, user)


__all__ = ["router"]
