"""Database connection pooling for improved performance and resource management."""

import asyncio
import aiosqlite
import logging
import os
import time
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class DatabasePool:
    """Connection pool for SQLite database operations."""
    
    def __init__(self, db_path: str, pool_size: int = 5, max_lifetime: int = 3600):
        """
        Initialize database connection pool.
        
        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of connections in pool
            max_lifetime: Maximum lifetime of a connection in seconds
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self.max_lifetime = max_lifetime
        self._pool: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=pool_size)
        self._created_connections = 0
        self._lock = asyncio.Lock()
        self._closed = False
        
        # Ensure directory exists
        dirpath = os.path.dirname(db_path) or "."
        os.makedirs(dirpath, exist_ok=True)
        
        logger.info(f"Initialized database pool: {db_path} (max_size: {pool_size})")
    
    async def _create_connection(self) -> Dict[str, Any]:
        """Create a new database connection with metadata."""
        conn = await aiosqlite.connect(
            self.db_path,
            timeout=10.0,
            check_same_thread=False
        )
        
        # Optimize performance
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA cache_size=10000")
        await conn.execute("PRAGMA temp_store=memory")
        await conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        
        connection_info = {
            'connection': conn,
            'created_at': time.time(),
            'last_used': time.time(),
            'usage_count': 0
        }
        
        self._created_connections += 1
        logger.debug(f"Created database connection #{self._created_connections}")
        
        return connection_info
    
    async def _is_connection_valid(self, conn_info: Dict[str, Any]) -> bool:
        """Check if a connection is still valid and not expired."""
        if self._closed:
            return False
        
        conn = conn_info['connection']
        created_at = conn_info['created_at']
        
        # Check if connection is expired
        if time.time() - created_at > self.max_lifetime:
            logger.debug("Connection expired, will be replaced")
            return False
        
        # Check if connection is still alive
        try:
            await conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.warning(f"Database connection check failed: {e}")
            return False
    
    @asynccontextmanager
    async def get_connection(self):
        """Get a connection from the pool using context manager."""
        if self._closed:
            raise RuntimeError("Database pool is closed")
        
        conn_info = None
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
            conn_info['last_used'] = time.time()
            conn_info['usage_count'] += 1
            
            yield conn_info['connection']
            
        finally:
            # Return connection to pool
            if conn_info and not self._closed:
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
    
    async def _close_connection(self, conn_info: Dict[str, Any]):
        """Close a single connection."""
        try:
            conn = conn_info['connection']
            if conn and not conn._closed:
                await conn.close()
            logger.debug("Closed database connection")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")
    
    async def close(self):
        """Close all connections in the pool."""
        self._closed = True
        
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
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        return {
            'pool_size': self._pool.qsize(),
            'max_pool_size': self.pool_size,
            'total_created': self._created_connections,
            'closed': self._closed,
            'db_path': self.db_path
        }


# Global pool instance
_global_pool: Optional[DatabasePool] = None
_pool_lock = asyncio.Lock()


async def get_database_pool(db_path: str, pool_size: int = 5) -> DatabasePool:
    """Get global database pool instance."""
    global _global_pool
    
    if _global_pool is None or _global_pool._closed:
        async with _pool_lock:
            if _global_pool is None or _global_pool._closed:
                _global_pool = DatabasePool(db_path, pool_size)
    
    return _global_pool


async def cleanup_database_pool():
    """Cleanup global database pool."""
    global _global_pool
    if _global_pool:
        await _global_pool.close()
        _global_pool = None


@asynccontextmanager
async def get_db_connection(db_path: str):
    """Get database connection from global pool."""
    pool = await get_database_pool(db_path)
    async with pool.get_connection() as conn:
        yield conn