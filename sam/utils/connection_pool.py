"""Database connection pooling for improved performance and resource management."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Deque, Dict, List, Optional, Tuple, TypedDict

import aiosqlite


logger = logging.getLogger(__name__)

# Feature flags and configuration
DEBUG_SQL = os.getenv("SAM_DEBUG_SQL", "0") == "1"
POOL_MIN_SIZE = int(os.getenv("SAM_DB_POOL_MIN_SIZE", "1"))
POOL_MAX_SIZE = int(os.getenv("SAM_DB_POOL_MAX_SIZE", "5"))
POOL_HEALTH_CHECK_INTERVAL = int(os.getenv("SAM_DB_POOL_HEALTH_CHECK_INTERVAL", "300"))  # 5 min


class ConnectionInfo(TypedDict):
    connection: aiosqlite.Connection
    created_at: float
    last_used: float
    usage_count: int


class PreparedStatementCache:
    """LRU cache for prepared SQL statements to improve performance."""

    def __init__(self, max_size: int = 50):
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._access_order: List[str] = []

    def get(self, sql: str) -> Optional[Any]:
        """Get cached prepared statement."""
        if sql in self._cache:
            # Move to end (most recently used)
            self._access_order.remove(sql)
            self._access_order.append(sql)
            return self._cache[sql]
        return None

    def put(self, sql: str, statement: Any) -> None:
        """Cache prepared statement with LRU eviction."""
        if sql in self._cache:
            # Update existing
            self._access_order.remove(sql)
        elif len(self._cache) >= self.max_size:
            # Evict least recently used
            lru_key = self._access_order.pop(0)
            del self._cache[lru_key]

        self._cache[sql] = statement
        self._access_order.append(sql)

    def clear(self) -> None:
        """Clear all cached statements."""
        self._cache.clear()
        self._access_order.clear()


async def execute_with_logging(
    conn: aiosqlite.Connection, sql: str, parameters: Optional[Tuple[Any, ...]] = None
) -> aiosqlite.Cursor:
    """Execute SQL query with optional debug logging.

    Args:
        conn: Database connection
        sql: SQL query string
        parameters: Optional query parameters

    Returns:
        Query cursor
    """
    if DEBUG_SQL:
        start_time = time.time()
        cursor = await conn.execute(sql, parameters or ())
        elapsed = (time.time() - start_time) * 1000  # ms
        params_str = str(parameters)[:100] if parameters else "None"
        logger.debug(f"SQL [{elapsed:.2f}ms]: {sql[:100]}... params={params_str}")
        return cursor
    else:
        return await conn.execute(sql, parameters or ())


class PoolStats(TypedDict):
    pool_size: int
    min_pool_size: int
    max_pool_size: int
    total_created: int
    total_acquired: int
    total_released: int
    total_health_checks: int
    failed_health_checks: int
    connections_replaced: int
    avg_connection_age: float
    avg_usage_count: float
    closed: bool
    db_path: str


class DatabasePool:
    """Enhanced connection pool with health checks and lifecycle hooks."""

    def __init__(
        self,
        db_path: str,
        pool_size: int = POOL_MAX_SIZE,
        min_size: int = POOL_MIN_SIZE,
        max_lifetime: int = 3600,
    ) -> None:
        """
        Initialize database connection pool.

        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of connections in pool
            min_size: Minimum number of connections to maintain
            max_lifetime: Maximum lifetime of a connection in seconds
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self.min_size = min_size
        self.max_lifetime = max_lifetime
        self._pool: asyncio.Queue[ConnectionInfo] = asyncio.Queue(maxsize=pool_size)
        self._created_connections = 0
        self._lock = asyncio.Lock()
        self._closed = False

        # Enhanced statistics
        self._total_acquired = 0
        self._total_released = 0
        self._total_health_checks = 0
        self._failed_health_checks = 0
        self._connections_replaced = 0

        # Lifecycle hooks
        self._on_connection_created: List[Callable[[aiosqlite.Connection], None]] = []
        self._on_connection_closed: List[Callable[[aiosqlite.Connection], None]] = []
        self._on_health_check_failed: List[Callable[[ConnectionInfo], None]] = []

        # Health check task
        self._health_check_task: Optional[asyncio.Task[None]] = None

        try:
            self._loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except Exception:
            self._loop = None

        # Ensure directory exists
        dirpath = os.path.dirname(db_path) or "."
        os.makedirs(dirpath, exist_ok=True)

        logger.info(
            f"Initialized database pool: {db_path} "
            f"(min: {min_size}, max: {pool_size}, lifetime: {max_lifetime}s)"
        )

        # Start health check task
        self._start_health_check_task()

    async def _create_connection(self) -> ConnectionInfo:
        """Create a new database connection with metadata."""
        max_retries = 3
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                import os as _os

                _timeout = 10.0 if _os.getenv("SAM_TEST_MODE") == "1" else 30.0
                conn = await aiosqlite.connect(
                    self.db_path, timeout=_timeout, check_same_thread=False
                )

                # Optimize performance with error handling
                try:
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA synchronous=NORMAL")
                    await conn.execute("PRAGMA cache_size=10000")
                    await conn.execute("PRAGMA temp_store=memory")
                    # Keep busy timeout conservative; shorter in test mode to prevent hangs
                    import os as _os

                    busy_ms = 2000 if _os.getenv("SAM_TEST_MODE") == "1" else 5000
                    await conn.execute(f"PRAGMA busy_timeout={busy_ms}")
                    await conn.execute("PRAGMA wal_autocheckpoint=1000")
                    # Enable mmap only when explicitly requested; safer default across OS/sandboxes
                    if _os.getenv("SAM_SQLITE_ENABLE_MMAP") == "1":
                        await conn.execute("PRAGMA mmap_size=268435456")  # 256MB
                    await conn.commit()
                except Exception as e:
                    logger.debug(f"Failed to set PRAGMA options: {e}")
                    # Continue with connection even if PRAGMA fails

                break

            except Exception as e:
                logger.warning(f"Database connection attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (2**attempt))

        connection_info: ConnectionInfo = {
            "connection": conn,
            "created_at": time.time(),
            "last_used": time.time(),
            "usage_count": 0,
        }

        self._created_connections += 1
        logger.debug(f"Created database connection #{self._created_connections}")

        # Trigger lifecycle hooks
        for hook in self._on_connection_created:
            try:
                hook(conn)
            except Exception as e:
                logger.error(f"Error in connection_created hook: {e}")

        return connection_info

    async def _is_connection_valid(
        self, conn_info: ConnectionInfo, track_stats: bool = True
    ) -> bool:
        """Check if a connection is still valid and not expired."""
        if self._closed:
            return False

        conn = conn_info["connection"]
        created_at = conn_info["created_at"]

        if track_stats:
            self._total_health_checks += 1

        # Check if connection is expired
        if time.time() - created_at > self.max_lifetime:
            logger.debug("Connection expired, will be replaced")
            if track_stats:
                self._failed_health_checks += 1
            return False

        # Check if connection is still alive with retry
        try:
            # Simple validation with timeout
            import os as _os

            _vto = 1.0 if _os.getenv("SAM_TEST_MODE") == "1" else 5.0
            await asyncio.wait_for(conn.execute("SELECT 1"), timeout=_vto)
            try:
                await conn.commit()
            except Exception:
                pass
            return True
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning(f"Database connection health check failed: {e}")
            if track_stats:
                self._failed_health_checks += 1
                # Trigger health check failed hooks
                for hook in self._on_health_check_failed:
                    try:
                        hook(conn_info)
                    except Exception as hook_error:
                        logger.error(f"Error in health_check_failed hook: {hook_error}")
            return False

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Get a connection from the pool using context manager."""
        if self._closed:
            raise RuntimeError("Database pool is closed")

        conn_info: Optional[ConnectionInfo] = None
        try:
            # Try to get connection from pool
            try:
                conn_info = self._pool.get_nowait()

                # Validate connection
                if not await self._is_connection_valid(conn_info):
                    await self._close_connection(conn_info)
                    conn_info = None
            except asyncio.QueueEmpty:
                pass

            # Create new connection if needed
            if conn_info is None:
                async with self._lock:
                    conn_info = await self._create_connection()

            # Update usage stats
            conn_info["last_used"] = time.time()
            conn_info["usage_count"] += 1
            self._total_acquired += 1

            yield conn_info["connection"]

        finally:
            # Return connection to pool
            if conn_info and not self._closed:
                self._total_released += 1
                try:
                    # Check if we can return it to pool
                    if await self._is_connection_valid(conn_info):
                        try:
                            self._pool.put_nowait(conn_info)
                        except asyncio.QueueFull:
                            # Pool is full, close this connection
                            await self._close_connection(conn_info)
                    else:
                        await self._close_connection(conn_info)
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
                    if conn_info:
                        await self._close_connection(conn_info)

    async def _close_connection(self, conn_info: ConnectionInfo) -> None:
        """Close a single connection with lifecycle hooks."""
        try:
            conn = conn_info.get("connection")
            if conn:
                # Trigger lifecycle hooks
                for hook in self._on_connection_closed:
                    try:
                        hook(conn)
                    except Exception as e:
                        logger.error(f"Error in connection_closed hook: {e}")

                try:
                    await conn.close()
                except Exception:
                    pass
            logger.debug("Closed database connection")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    async def close(self) -> None:
        """Close all connections in the pool and stop health check task."""
        self._closed = True
        self._loop = None

        # Cancel health check task
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        closed_count = 0
        while not self._pool.empty():
            try:
                conn_info = self._pool.get_nowait()
                await self._close_connection(conn_info)
                closed_count += 1
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error(f"Error closing pooled connection: {e}")

        logger.info(f"Closed database pool: {closed_count} connections")

    async def get_stats(self) -> PoolStats:
        """Get enhanced pool statistics."""
        # Calculate average connection age and usage
        async with self._lock:
            connections = []
            temp_queue: Deque[ConnectionInfo] = deque()

            # Collect all connections from pool temporarily
            while not self._pool.empty():
                try:
                    conn_info = self._pool.get_nowait()
                    connections.append(conn_info)
                    temp_queue.append(conn_info)
                except asyncio.QueueEmpty:
                    break

            # Put them back
            for conn_info in temp_queue:
                try:
                    self._pool.put_nowait(conn_info)
                except asyncio.QueueFull:
                    break

            # Calculate averages
            current_time = time.time()
            avg_age = (
                sum(current_time - c["created_at"] for c in connections) / len(connections)
                if connections
                else 0
            )
            avg_usage = (
                sum(c["usage_count"] for c in connections) / len(connections) if connections else 0
            )

        return {
            "pool_size": self._pool.qsize(),
            "min_pool_size": self.min_size,
            "max_pool_size": self.pool_size,
            "total_created": self._created_connections,
            "total_acquired": self._total_acquired,
            "total_released": self._total_released,
            "total_health_checks": self._total_health_checks,
            "failed_health_checks": self._failed_health_checks,
            "connections_replaced": self._connections_replaced,
            "avg_connection_age": avg_age,
            "avg_usage_count": avg_usage,
            "closed": self._closed,
            "db_path": self.db_path,
        }

    def on_connection_created(self, callback: Callable[[aiosqlite.Connection], None]) -> None:
        """Register a callback for when a connection is created.

        Args:
            callback: Function to call with the new connection
        """
        self._on_connection_created.append(callback)

    def on_connection_closed(self, callback: Callable[[aiosqlite.Connection], None]) -> None:
        """Register a callback for when a connection is closed.

        Args:
            callback: Function to call with the closing connection
        """
        self._on_connection_closed.append(callback)

    def on_health_check_failed(self, callback: Callable[[ConnectionInfo], None]) -> None:
        """Register a callback for when a health check fails.

        Args:
            callback: Function to call with the failed connection info
        """
        self._on_health_check_failed.append(callback)

    def _start_health_check_task(self) -> None:
        """Start periodic health check task."""
        try:
            asyncio.get_running_loop()
            self._health_check_task = asyncio.create_task(self._periodic_health_check())
        except RuntimeError:
            # No running loop yet
            pass

    async def _periodic_health_check(self) -> None:
        """Periodically check health of pooled connections."""
        while not self._closed:
            try:
                await asyncio.sleep(POOL_HEALTH_CHECK_INTERVAL)

                if self._closed:
                    break

                # Check all connections in pool
                async with self._lock:
                    invalid_connections: List[ConnectionInfo] = []
                    valid_connections: List[ConnectionInfo] = []

                    while not self._pool.empty():
                        try:
                            conn_info = self._pool.get_nowait()

                            if await self._is_connection_valid(conn_info, track_stats=True):
                                valid_connections.append(conn_info)
                            else:
                                invalid_connections.append(conn_info)
                        except asyncio.QueueEmpty:
                            break

                    # Close invalid connections
                    for conn_info in invalid_connections:
                        await self._close_connection(conn_info)
                        self._connections_replaced += 1

                    # Return valid connections to pool
                    for conn_info in valid_connections:
                        try:
                            self._pool.put_nowait(conn_info)
                        except asyncio.QueueFull:
                            await self._close_connection(conn_info)

                    if invalid_connections:
                        logger.info(
                            f"Health check: replaced {len(invalid_connections)} connections, "
                            f"kept {len(valid_connections)} healthy"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in pool health check: {e}")


# Global pool instance
_global_pool: Optional[DatabasePool] = None
_pool_lock: Optional[asyncio.Lock] = None


def _get_pool_lock() -> asyncio.Lock:
    """Get or create the pool initialization lock."""
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def get_database_pool(db_path: str, pool_size: int = 5) -> DatabasePool:
    """Get global database pool instance (thread-safe with double-check locking)."""
    global _global_pool

    current_loop = None
    try:
        current_loop = asyncio.get_running_loop()
    except Exception:
        pass

    # Helper to check if pool needs recreation
    def needs_new_pool() -> bool:
        return (
            _global_pool is None
            or _global_pool._closed
            or _global_pool._loop is None
            or (_global_pool._loop and _global_pool._loop.is_closed())
            or (
                _global_pool._loop is not None
                and current_loop is not None
                and _global_pool._loop is not current_loop
            )
        )

    # Fast path - pool is valid
    if not needs_new_pool():
        assert _global_pool is not None
        return _global_pool

    # Acquire lock for initialization/recreation
    lock = _get_pool_lock()
    async with lock:
        # Double-check inside lock
        if not needs_new_pool():
            assert _global_pool is not None
            return _global_pool

        # Close old pool if exists
        if _global_pool and not _global_pool._closed:
            try:
                await _global_pool.close()
            except Exception as e:
                logger.warning(f"Error closing old database pool: {e}")

        # Create new pool
        _global_pool = DatabasePool(db_path, pool_size)
        assert _global_pool is not None
        return _global_pool


async def cleanup_database_pool() -> None:
    """Cleanup global database pool (thread-safe)."""
    global _global_pool, _pool_lock

    if _global_pool is None:
        return

    lock = _get_pool_lock()
    async with lock:
        if _global_pool:
            await _global_pool.close()
            _global_pool = None
        # Reset lock for potential re-initialization
        _pool_lock = None


@asynccontextmanager
async def get_db_connection(db_path: str) -> AsyncIterator[aiosqlite.Connection]:
    """Get database connection from global pool."""
    pool = await get_database_pool(db_path)
    async with pool.get_connection() as conn:
        yield conn
