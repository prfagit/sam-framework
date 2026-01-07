"""FastAPI application factory for the SAM Framework API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config.settings import Settings
from .middleware.csrf import CSRFMiddleware
from .middleware.request_id import RequestIDMiddleware
from ..web.session import close_agent
from .routes import register_routes

logger = logging.getLogger(__name__)


def create_app(extra_app_kwargs: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""

    # Reload settings in case env vars changed before app startup
    Settings.refresh_from_env()

    app_kwargs: dict[str, Any] = {
        "title": "SAM Framework API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "root_path": Settings.SAM_API_ROOT_PATH or "",
    }
    if extra_app_kwargs:
        app_kwargs.update(extra_app_kwargs)

    app = FastAPI(**app_kwargs)

    # Always enable CORS middleware
    # Security: Never allow ["*"] with credentials - require explicit origins
    cors_origins = Settings.SAM_API_CORS_ORIGINS

    # In development, if no origins are set, allow common localhost origins
    # In production, this should always be explicitly set
    if not cors_origins:
        import os

        # Only allow wildcard in development mode (when explicitly set)
        if os.getenv("SAM_DEV_MODE") == "1":
            logger.warning(
                "CORS: Allowing all origins (SAM_DEV_MODE=1). "
                "This is insecure for production. Set SAM_API_CORS_ORIGINS explicitly."
            )
            cors_origins = ["*"]
        else:
            # Default to common development origins
            cors_origins = [
                "http://localhost:3000",
                "http://localhost:3001",
                "http://localhost:5173",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3001",
                "http://127.0.0.1:5173",
            ]
            logger.info(
                "CORS: Using default development origins. "
                "Set SAM_API_CORS_ORIGINS for production or SAM_DEV_MODE=1 for wildcard."
            )

    # Security: Cannot use allow_credentials=True with allow_origins=["*"]
    # If wildcard is used, disable credentials
    allow_creds = True
    if "*" in cors_origins:
        allow_creds = False
        logger.warning(
            "CORS: Wildcard origins detected. Credentials disabled for security. "
            "Set explicit origins to enable credentials."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_creds,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-CSRF-Token", "X-Request-ID"],
    )

    # Request ID middleware (first, so all requests have an ID)
    app.add_middleware(RequestIDMiddleware)

    # CSRF protection middleware (after CORS)
    app.add_middleware(CSRFMiddleware)

    register_routes(app)

    @app.on_event("startup")
    async def _startup() -> None:  # pragma: no cover - side effect only
        logger.info(
            "Starting SAM API on %s:%s (root_path=%s)",
            Settings.SAM_API_HOST,
            Settings.SAM_API_PORT,
            Settings.SAM_API_ROOT_PATH or "/",
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover - side effect only
        logger.info("Shutting down SAM API")
        try:
            await close_agent()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to close cached agent cleanly: %s", exc)

    return app


# Create app instance for uvicorn
app = create_app()

__all__ = ["create_app", "app"]
