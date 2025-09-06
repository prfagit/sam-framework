import pytest
import asyncio
import tempfile
import os
from unittest.mock import patch, MagicMock, AsyncMock
from sam.utils.connection_pool import (
    DatabasePool, get_database_pool, cleanup_database_pool,
    get_db_connection
)


class TestDatabasePool:
    """Test DatabasePool class functionality."""

    @pytest.fixture
    async def db_pool(self):
        """Create a test database pool."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            pool = DatabasePool(db_path, pool_size=3, max_lifetime=60)
            yield pool
            # Cleanup
            if not pool._closed:
                await pool.close()

    @pytest.mark.asyncio
    async def test_pool_initialization(self, db_pool):
        """Test database pool initialization."""
        assert db_pool.db_path.endswith("test.db")
        assert db_pool.pool_size == 3
        assert db_pool.max_lifetime == 60
        assert db_pool._created_connections == 0
        assert db_pool._closed is False

    @pytest.mark.asyncio
    async def test_create_connection(self, db_pool):
        """Test connection creation."""
        conn_info = await db_pool._create_connection()

        assert 'connection' in conn_info
        assert 'created_at' in conn_info
        assert 'last_used' in conn_info
        assert 'usage_count' in conn_info
        assert conn_info['usage_count'] == 0
        assert isinstance(conn_info['created_at'], float)

        # Cleanup
        await conn_info['connection'].close()

    @pytest.mark.asyncio
    async def test_connection_validation_valid(self, db_pool):
        """Test connection validation for valid connection."""
        conn_info = await db_pool._create_connection()

        is_valid = await db_pool._is_connection_valid(conn_info)

        assert is_valid is True

        # Cleanup
        await conn_info['connection'].close()

    @pytest.mark.asyncio
    async def test_connection_validation_expired(self, db_pool):
        """Test connection validation for expired connection."""
        conn_info = await db_pool._create_connection()

        # Make connection appear expired
        conn_info['created_at'] = 0  # Very old timestamp

        is_valid = await db_pool._is_connection_valid(conn_info)

        assert is_valid is False

    @pytest.mark.asyncio
    async def test_connection_validation_closed_pool(self, db_pool):
        """Test connection validation when pool is closed."""
        conn_info = await db_pool._create_connection()
        db_pool._closed = True

        is_valid = await db_pool._is_connection_valid(conn_info)

        assert is_valid is False

    @pytest.mark.asyncio
    async def test_get_connection_from_empty_pool(self, db_pool):
        """Test getting connection when pool is empty."""
        async with db_pool.get_connection() as conn:
            assert conn is not None

        # Check that connection was returned to pool
        assert db_pool._pool.qsize() == 1

    @pytest.mark.asyncio
    async def test_get_connection_reuse_from_pool(self, db_pool):
        """Test reusing connection from pool."""
        # First connection
        async with db_pool.get_connection() as conn1:
            assert conn1 is not None

        # Second connection should reuse the first
        async with db_pool.get_connection() as conn2:
            assert conn2 is not None

        # Pool should still have 1 connection
        assert db_pool._pool.qsize() == 1

    @pytest.mark.asyncio
    async def test_get_connection_pool_full(self, db_pool):
        """Test connection handling when pool is full."""
        # Fill the pool
        connections = []
        for i in range(3):  # pool_size = 3
            conn_ctx = db_pool.get_connection()
            conn = await conn_ctx.__aenter__()
            connections.append((conn_ctx, conn))

        # Next connection should create a new one (not from pool)
        async with db_pool.get_connection() as conn4:
            assert conn4 is not None

        # Close all connections
        for conn_ctx, conn in connections:
            await conn_ctx.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_get_connection_closed_pool(self, db_pool):
        """Test getting connection from closed pool."""
        await db_pool.close()

        with pytest.raises(RuntimeError, match="Database pool is closed"):
            async with db_pool.get_connection():
                pass

    @pytest.mark.asyncio
    async def test_close_pool(self, db_pool):
        """Test closing database pool."""
        # Add a connection to the pool
        async with db_pool.get_connection():
            pass

        assert db_pool._pool.qsize() == 1

        await db_pool.close()

        assert db_pool._closed is True
        assert db_pool._pool.qsize() == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, db_pool):
        """Test getting pool statistics."""
        stats = await db_pool.get_stats()

        expected_keys = ['pool_size', 'max_pool_size', 'total_created', 'closed', 'db_path']
        for key in expected_keys:
            assert key in stats

        assert stats['max_pool_size'] == 3
        assert stats['db_path'] == db_pool.db_path
        assert stats['closed'] is False


class TestGlobalConnectionPool:
    """Test global connection pool functions."""

    @pytest.mark.asyncio
    async def test_get_database_pool_singleton(self):
        """Test global database pool singleton pattern."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")

            # Reset global state
            import sam.utils.connection_pool
            sam.utils.connection_pool._global_pool = None

            pool1 = await get_database_pool(db_path)
            pool2 = await get_database_pool(db_path)

            assert pool1 is pool2
            assert isinstance(pool1, DatabasePool)

            # Cleanup
            await pool1.close()

    @pytest.mark.asyncio
    async def test_get_database_pool_different_paths(self):
        """Test getting different pools for different database paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path1 = os.path.join(temp_dir, "test1.db")
            db_path2 = os.path.join(temp_dir, "test2.db")

            # Reset global state
            import sam.utils.connection_pool
            sam.utils.connection_pool._global_pool = None

            pool1 = await get_database_pool(db_path1)

            # Change global pool to None to force creation of new pool
            sam.utils.connection_pool._global_pool = None

            pool2 = await get_database_pool(db_path2)

            assert pool1 is not pool2
            assert pool1.db_path == db_path1
            assert pool2.db_path == db_path2

            # Cleanup
            await pool1.close()
            await pool2.close()

    @pytest.mark.asyncio
    async def test_cleanup_database_pool(self):
        """Test cleanup of global database pool."""
        import sam.utils.connection_pool
        mock_pool = AsyncMock()
        sam.utils.connection_pool._global_pool = mock_pool

        await cleanup_database_pool()

        mock_pool.close.assert_called_once()
        assert sam.utils.connection_pool._global_pool is None

    @pytest.mark.asyncio
    async def test_get_db_connection_context_manager(self):
        """Test database connection context manager."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")

            # Reset global state
            import sam.utils.connection_pool
            sam.utils.connection_pool._global_pool = None

            async with get_db_connection(db_path) as conn:
                assert conn is not None

            # Pool should be created and have a connection
            pool = await get_database_pool(db_path)
            assert pool._pool.qsize() == 1


class TestConnectionPoolIntegration:
    """Test connection pool integration scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_connection_usage(self):
        """Test concurrent usage of database connections."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            pool = DatabasePool(db_path, pool_size=5)

            async def use_connection(task_id):
                async with pool.get_connection() as conn:
                    # Simulate some work
                    await asyncio.sleep(0.01)
                    return f"task_{task_id}_done"

            # Run multiple concurrent tasks
            tasks = [use_connection(i) for i in range(10)]
            results = await asyncio.gather(*tasks)

            assert len(results) == 10
            assert all("done" in result for result in results)

            # Pool should have connections available
            assert pool._pool.qsize() <= 5  # Should not exceed pool size

            await pool.close()

    @pytest.mark.asyncio
    async def test_connection_lifecycle(self):
        """Test full connection lifecycle."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            pool = DatabasePool(db_path, pool_size=2, max_lifetime=1)  # Short lifetime

            # Create and use connection
            async with pool.get_connection() as conn:
                assert conn is not None

            # Wait for connection to expire
            await asyncio.sleep(1.1)

            # Next connection should create a new one (old one should be invalid)
            async with pool.get_connection() as conn:
                assert conn is not None

            await pool.close()


if __name__ == "__main__":
    pytest.main([__file__])
