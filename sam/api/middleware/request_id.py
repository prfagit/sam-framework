"""Request ID middleware for request tracing and correlation."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable to store request ID for the current request
# This allows access to the request ID from anywhere in the application
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

# Header names for request ID
REQUEST_ID_HEADER = "X-Request-ID"
RESPONSE_ID_HEADER = "X-Request-ID"


def get_request_id() -> Optional[str]:
    """Get the current request ID from context.

    Returns:
        Current request ID or None if not in a request context
    """
    return request_id_ctx.get()


def generate_request_id() -> str:
    """Generate a new unique request ID.

    Returns:
        UUID-based request ID
    """
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a unique request ID to each request.

    This middleware:
    1. Extracts request ID from incoming X-Request-ID header (if present)
    2. Generates a new request ID if not provided
    3. Stores the request ID in context for use throughout the request
    4. Adds the request ID to the response headers

    The request ID can be used for:
    - Request tracing across services
    - Log correlation
    - Debugging and troubleshooting
    - Audit trails
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get existing request ID from header or generate new one
        request_id = request.headers.get(REQUEST_ID_HEADER)

        if not request_id:
            request_id = generate_request_id()

        # Store in context for access throughout the request
        token = request_id_ctx.set(request_id)

        try:
            # Store in request state for easy access
            request.state.request_id = request_id

            # Process the request
            response = await call_next(request)

            # Add request ID to response headers
            response.headers[RESPONSE_ID_HEADER] = request_id

            return response
        finally:
            # Reset context variable
            request_id_ctx.reset(token)


class RequestIDLogFilter:
    """Logging filter that adds request ID to log records.

    Usage:
        import logging

        handler = logging.StreamHandler()
        handler.addFilter(RequestIDLogFilter())
        handler.setFormatter(
            logging.Formatter('%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s')
        )
        logger.addHandler(handler)
    """

    def filter(self, record) -> bool:
        """Add request_id to log record."""
        record.request_id = get_request_id() or "-"
        return True


__all__ = [
    "RequestIDMiddleware",
    "RequestIDLogFilter",
    "get_request_id",
    "generate_request_id",
    "request_id_ctx",
    "REQUEST_ID_HEADER",
]
