"""Health endpoints."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import Optional

from fastapi import APIRouter

from ...config.settings import Settings
from ..public_storage import get_public_storage

router = APIRouter(prefix="", tags=["health"])
logger = logging.getLogger(__name__)


def _package_version() -> str:
    try:
        return importlib.metadata.version("sam-framework")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev installs
        return "0.0.0"


async def _get_marketplace_stats() -> Optional[dict[str, int]]:
    """Get marketplace statistics for health check."""
    try:
        storage = get_public_storage(Settings.SAM_DB_PATH)
        _, total = await storage.list_public_agents(limit=0, offset=0)
        return {"public_agents": total}
    except Exception as e:
        logger.debug("Failed to get marketplace stats: %s", e)
        return None


@router.get("/health", summary="API health status")
async def health_status() -> dict[str, object]:
    marketplace = await _get_marketplace_stats()
    return {
        "status": "ok",
        "version": _package_version(),
        "llm_provider": Settings.LLM_PROVIDER,
        "marketplace": marketplace,
    }


__all__ = ["router"]
