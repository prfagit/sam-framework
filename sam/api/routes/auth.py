"""Wallet-based authentication endpoints.

This module provides endpoints for Solana wallet authentication using
Ed25519 signature verification. Users authenticate by signing a challenge
message with their Phantom/Solflare wallet.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from ...utils.rate_limiter import check_rate_limit
from ...utils.wallet_auth import validate_wallet_address
from ..auth import (
    create_access_token,
    create_refresh_token,
    create_wallet_challenge,
    revoke_refresh_token,
    verify_refresh_token,
    verify_wallet_challenge,
)
from ..schemas import (
    ChallengeRequest,
    ChallengeResponse,
    LogoutRequest,
    RefreshTokenRequest,
    TokenResponse,
    VerifyRequest,
)

# Cookie configuration
COOKIE_NAME = "sam_refresh_token"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds
COOKIE_SECURE = os.getenv("SAM_DEV_MODE", "0") != "1"  # Secure in production
COOKIE_SAMESITE = "lax"  # Protection against CSRF while allowing normal navigation

# Security: Only include refresh token in response body during dev mode
INCLUDE_REFRESH_IN_BODY = os.getenv("SAM_DEV_MODE", "0") == "1"

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/auth", tags=["auth"])


async def _get_client_identifier(request: Request) -> str:
    """Get client identifier for rate limiting from request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set HttpOnly cookie with refresh token."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=refresh_token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/v1/auth",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


@router.post("/challenge", response_model=ChallengeResponse)
async def get_challenge(data: ChallengeRequest, request: Request) -> ChallengeResponse:
    """Get a challenge message to sign with wallet.

    This is the first step of wallet authentication:
    1. Frontend connects to wallet
    2. Frontend calls this endpoint with wallet address
    3. Backend returns a message containing a nonce
    4. Frontend asks wallet to sign the message
    5. Frontend calls /verify with the signature
    """
    # Rate limiting to prevent abuse
    client_id = await _get_client_identifier(request)
    allowed, rate_info = await check_rate_limit(
        identifier=f"auth:challenge:{client_id}",
        limit_type="auth_login",  # Use same limits as login
    )

    if not allowed:
        retry_after = int(rate_info.get("retry_after", 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # Validate wallet address format
    if not validate_wallet_address(data.wallet_address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wallet address format",
        )

    try:
        challenge = await create_wallet_challenge(data.wallet_address)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return ChallengeResponse(
        message=challenge.message,
        nonce=challenge.nonce,
        expires_at=challenge.expires_at,
    )


@router.post("/verify", response_model=TokenResponse)
async def verify_signature(
    data: VerifyRequest, request: Request, response: Response
) -> TokenResponse:
    """Verify wallet signature and issue tokens.

    This is the second step of wallet authentication:
    1. Frontend sends wallet_address, signature, and nonce
    2. Backend verifies the signature
    3. Backend creates/retrieves user account
    4. Backend issues JWT tokens
    """
    print(
        f"[VERIFY] Received: wallet={data.wallet_address[:8]}..., nonce={data.nonce[:8]}..., sig_len={len(data.signature)}"
    )

    # Rate limiting
    client_id = await _get_client_identifier(request)
    allowed, rate_info = await check_rate_limit(
        identifier=f"auth:verify:{client_id}",
        limit_type="auth_login",
    )

    if not allowed:
        retry_after = int(rate_info.get("retry_after", 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many verification attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # Validate wallet address
    if not validate_wallet_address(data.wallet_address):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wallet address format",
        )

    # Verify signature and authenticate
    user = await verify_wallet_challenge(data.wallet_address, data.signature, data.nonce)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature or expired challenge",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create tokens
    token, expires = create_access_token(
        wallet_address=user.wallet_address,
        user_id=user.user_id,
    )
    refresh_token, refresh_expires = await create_refresh_token(
        wallet_address=user.wallet_address,
        user_id=user.user_id,
    )

    # Set refresh token as HttpOnly cookie
    _set_refresh_cookie(response, refresh_token)

    logger.info(f"Wallet authenticated: {user.wallet_address[:8]}...")

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires.isoformat(),
        refresh_token=refresh_token if INCLUDE_REFRESH_IN_BODY else None,
        refresh_expires_at=refresh_expires.isoformat(),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    data: RefreshTokenRequest | None = None,
    sam_refresh_token: str | None = Cookie(None),
) -> TokenResponse:
    """Refresh an access token using a refresh token.

    Accepts refresh token from:
    1. HttpOnly cookie (preferred, more secure)
    2. Request body (for backwards compatibility)
    """
    client_id = await _get_client_identifier(request)
    allowed, rate_info = await check_rate_limit(
        identifier=f"auth:refresh:{client_id}",
        limit_type="auth_refresh",
    )

    if not allowed:
        retry_after = int(rate_info.get("retry_after", 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many refresh attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # Get refresh token from cookie or body
    token_to_verify = sam_refresh_token
    if not token_to_verify and data and data.refresh_token:
        token_to_verify = data.refresh_token

    if not token_to_verify:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify the refresh token
    user = await verify_refresh_token(token_to_verify)
    if not user:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create new tokens (token rotation)
    new_access_token, expires = create_access_token(
        wallet_address=user.wallet_address,
        user_id=user.user_id,
    )
    new_refresh_token, refresh_expires = await create_refresh_token(
        wallet_address=user.wallet_address,
        user_id=user.user_id,
    )

    # Revoke old refresh token
    await revoke_refresh_token(token_to_verify)

    # Set new refresh token cookie
    _set_refresh_cookie(response, new_refresh_token)

    return TokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_at=expires.isoformat(),
        refresh_token=new_refresh_token if INCLUDE_REFRESH_IN_BODY else None,
        refresh_expires_at=refresh_expires.isoformat(),
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    data: LogoutRequest | None = None,
    sam_refresh_token: str | None = Cookie(None),
) -> dict[str, str]:
    """Logout by revoking a refresh token.

    Accepts refresh token from:
    1. HttpOnly cookie (preferred)
    2. Request body (for backwards compatibility)
    """
    token_to_revoke = sam_refresh_token
    if not token_to_revoke and data and data.refresh_token:
        token_to_revoke = data.refresh_token

    if token_to_revoke:
        revoked = await revoke_refresh_token(token_to_revoke)
        if not revoked:
            logger.debug("Refresh token not found or already revoked")

    _clear_refresh_cookie(response)

    return {"message": "Logged out successfully"}


__all__ = ["router"]
