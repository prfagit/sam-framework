"""CSRF protection middleware using double-submit cookie pattern."""

from __future__ import annotations

import os
import secrets
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# CSRF configuration
CSRF_COOKIE_NAME = "sam_csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days
CSRF_COOKIE_SECURE = os.getenv("SAM_DEV_MODE", "0") != "1"
CSRF_COOKIE_SAMESITE = "lax"

# Routes that require CSRF protection (state-changing POST/PUT/DELETE endpoints)
PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Routes exempt from CSRF check (auth endpoints must work without token initially)
# Note: These endpoints have their own security (wallet signature verification, JWT)
EXEMPT_ROUTES = {
    "/v1/auth/challenge",  # Wallet auth: get sign-in challenge
    "/v1/auth/verify",  # Wallet auth: verify signature
    "/v1/auth/refresh",
    "/v1/auth/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
}

# Route prefixes exempt from CSRF
# SECURITY: We removed /v1/agents/ and /v1/sessions/ - they need CSRF protection
# as they are state-changing endpoints. JWT auth alone is not sufficient against CSRF.
# Only truly safe prefixes (read-only public endpoints) should be here.
EXEMPT_PREFIXES = (
    "/v1/agents/public/",  # Public marketplace browsing (GET only, POST still checked)
    "/v1/agents/shared/",  # Shared agent access (GET only)
)


def generate_csrf_token() -> str:
    """Generate a secure random CSRF token."""
    return secrets.token_urlsafe(32)


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection using double-submit cookie pattern.

    This middleware:
    1. Sets a CSRF token in a non-HttpOnly cookie (readable by JavaScript)
    2. Requires the token to be sent in X-CSRF-Token header for state-changing requests
    3. Verifies the cookie and header values match
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip CSRF check for safe methods
        if request.method not in PROTECTED_METHODS:
            response = await call_next(request)
            # Ensure CSRF cookie is set for GET requests
            self._ensure_csrf_cookie(request, response)
            return response

        # Skip CSRF check for exempt routes
        if request.url.path in EXEMPT_ROUTES:
            response = await call_next(request)
            # Set CSRF cookie on login/register responses
            self._ensure_csrf_cookie(request, response)
            return response

        # Skip CSRF check for exempt prefixes (dynamic routes)
        if request.url.path.startswith(EXEMPT_PREFIXES):
            response = await call_next(request)
            return response

        # Validate CSRF token for state-changing requests
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_header = request.headers.get(CSRF_HEADER_NAME)

        if not csrf_cookie or not csrf_header:
            return Response(
                content='{"detail": "CSRF token missing"}',
                status_code=403,
                media_type="application/json",
            )

        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(csrf_cookie, csrf_header):
            return Response(
                content='{"detail": "CSRF token invalid"}',
                status_code=403,
                media_type="application/json",
            )

        response = await call_next(request)
        return response

    def _ensure_csrf_cookie(self, request: Request, response: Response) -> None:
        """Ensure CSRF cookie is set, generating a new one if needed."""
        existing_token = request.cookies.get(CSRF_COOKIE_NAME)

        if not existing_token:
            token = generate_csrf_token()
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=token,
                max_age=CSRF_COOKIE_MAX_AGE,
                httponly=False,  # Must be readable by JavaScript
                secure=CSRF_COOKIE_SECURE,
                samesite=CSRF_COOKIE_SAMESITE,
                path="/",
            )


__all__ = ["CSRFMiddleware", "CSRF_COOKIE_NAME", "CSRF_HEADER_NAME"]
