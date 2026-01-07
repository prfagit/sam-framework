"""Shared dependency helpers for the FastAPI surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from ..core.context import RequestContext
from .auth import User, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/verify")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/v1/auth/verify", auto_error=False)


@dataclass(slots=True)
class APIUser:
    """Resolved user identity for API interactions."""

    wallet_address: str
    user_id: str
    is_admin: bool


def _to_api_user(user: User) -> APIUser:
    return APIUser(wallet_address=user.wallet_address, user_id=user.user_id, is_admin=user.is_admin)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> APIUser:
    """Resolve the API user from the provided bearer token."""

    try:
        user = await decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return _to_api_user(user)


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
) -> Optional[APIUser]:
    """Optionally resolve the API user if a token is provided.

    Unlike get_current_user, this does not raise an error if no token is provided.
    Returns None for unauthenticated requests.
    """
    if not token:
        return None

    try:
        user = await decode_access_token(token)
        return _to_api_user(user)
    except ValueError:
        # Invalid token - treat as unauthenticated
        return None


async def get_request_context(user: APIUser = Depends(get_current_user)) -> RequestContext:
    """Build a RequestContext for downstream agent orchestration."""

    return RequestContext(user_id=user.user_id)


__all__ = ["APIUser", "get_current_user", "get_current_user_optional", "get_request_context"]
