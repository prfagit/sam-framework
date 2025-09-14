"""Shared HTTP client for consistent session management across integrations."""

import logging
import aiohttp
import asyncio
from typing import Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class SharedHTTPClient:
    """Shared HTTP client with connection pooling and resource management."""

    _instance: Optional["SharedHTTPClient"] = None
    _session: Optional[aiohttp.ClientSession] = None

    def __init__(self):
        self._closed = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    async def get_instance(cls) -> "SharedHTTPClient":
        """Get singleton instance of shared HTTP client.

        Avoids cross-loop locks to remain compatible with reruns; in practice,
        a single instance per process is sufficient.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session with optimized settings.

        Recreates the session if the associated event loop is different or closed
        (common in Streamlit reruns or when using asyncio.run multiple times).
        """
        current_loop = asyncio.get_running_loop()
        recreate = False
        if self._session is None or self._closed:
            recreate = True
        else:
            # If the loop changed or is closed, drop and recreate the session
            if self._loop is None or self._loop.is_closed() or self._loop is not current_loop:
                try:
                    if self._session and not self._session.closed:
                        await self._session.close()
                except Exception:
                    pass
                self._session = None
                recreate = True

        if recreate:
            await self._create_session()
        assert self._session is not None, "Session should be created by _create_session"
        return self._session

    async def _create_session(self):
        """Create new HTTP session with optimized settings."""
        # Connection pooling and timeout configuration
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection limit
            limit_per_host=20,  # Per-host connection limit
            ttl_dns_cache=300,  # DNS cache TTL
            use_dns_cache=True,
            keepalive_timeout=30,
            enable_cleanup_closed=True,
        )

        # Shorter defaults in test mode to avoid long hangs
        import os as _os
        if _os.getenv("SAM_TEST_MODE") == "1":
            timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=10)
        else:
            timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)

        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "SAM-Framework/0.1.0"},
            trust_env=True,  # honor HTTP(S)_PROXY and system SSL settings
        )

        logger.info("Created shared HTTP session with connection pooling")
        self._closed = False
        try:
            self._loop = asyncio.get_running_loop()
        except Exception:
            self._loop = None

    @asynccontextmanager
    async def request(self, method: str, url: str, **kwargs):
        """Context manager for making HTTP requests with automatic cleanup."""
        session = await self.get_session()
        try:
            async with session.request(method, url, **kwargs) as response:
                yield response
        except Exception as e:
            logger.error(f"HTTP request failed: {method} {url} - {e}")
            raise

    async def close(self):
        """Close HTTP session and cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Closed shared HTTP session")
        self._closed = True
        self._loop = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Global instance functions
_global_client: Optional[SharedHTTPClient] = None


async def get_http_client() -> SharedHTTPClient:
    """Get global HTTP client instance."""
    global _global_client
    if _global_client is None:
        _global_client = await SharedHTTPClient.get_instance()
    return _global_client


async def cleanup_http_client():
    """Cleanup global HTTP client."""
    global _global_client
    if _global_client:
        await _global_client.close()
        _global_client = None


# Convenience functions
async def get_session() -> aiohttp.ClientSession:
    """Get HTTP session from global client."""
    client = await get_http_client()
    return await client.get_session()


@asynccontextmanager
async def http_request(method: str, url: str, **kwargs):
    """Make HTTP request using global shared client."""
    client = await get_http_client()
    async with client.request(method, url, **kwargs) as response:
        yield response
