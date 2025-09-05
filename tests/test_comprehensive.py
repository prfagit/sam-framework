"""Comprehensive integration tests for improved SAM framework components."""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch

# Test imports
from sam.utils.http_client import SharedHTTPClient, get_http_client, cleanup_http_client
from sam.utils.connection_pool import DatabasePool, get_database_pool, cleanup_database_pool
from sam.utils.rate_limiter import RateLimiter, cleanup_rate_limiter
from sam.utils.enhanced_decorators import safe_async_operation, performance_monitor
from sam.utils.error_handling import ErrorSeverity
from sam.core.memory import MemoryManager


class TestHTTPClientIntegration:
    """Test shared HTTP client functionality."""
    
    @pytest.mark.asyncio
    async def test_shared_http_client_singleton(self):
        """Test that shared HTTP client returns same instance."""
        client1 = await get_http_client()
        client2 = await get_http_client()
        assert client1 is client2
    
    @pytest.mark.asyncio
    async def test_http_client_session_creation(self):
        """Test HTTP session creation and configuration."""
        client = await get_http_client()
        session = await client.get_session()
        
        assert session is not None
        assert session.timeout.total == 60
        assert not session.closed
        
        await cleanup_http_client()
    
    @pytest.mark.asyncio
    async def test_http_client_cleanup(self):
        """Test proper cleanup of HTTP client."""
        client = await get_http_client()
        session = await client.get_session()
        
        await cleanup_http_client()
        assert session.closed


class TestDatabasePoolIntegration:
    """Test database connection pooling."""
    
    @pytest.mark.asyncio
    async def test_database_pool_creation(self):
        """Test database pool initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            pool = DatabasePool(db_path, pool_size=3)
            
            assert pool.pool_size == 3
            assert pool.db_path == db_path
            
            await pool.close()
    
    @pytest.mark.asyncio
    async def test_database_connection_usage(self):
        """Test getting and using database connections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            pool = DatabasePool(db_path, pool_size=2)
            
            async with pool.get_connection() as conn:
                # Test basic database operation
                cursor = await conn.execute("SELECT 1 as test")
                result = await cursor.fetchone()
                assert result[0] == 1
            
            await pool.close()
    
    @pytest.mark.asyncio
    async def test_connection_pool_stats(self):
        """Test connection pool statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            pool = DatabasePool(db_path)
            
            stats = await pool.get_stats()
            assert stats['max_pool_size'] == 5
            assert stats['pool_size'] == 0
            assert stats['total_created'] == 0
            assert not stats['closed']
            
            await pool.close()


class TestRateLimiterOptimizations:
    """Test optimized rate limiter functionality."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_basic_functionality(self):
        """Test basic rate limiting."""
        limiter = RateLimiter(max_keys=100, cleanup_interval=1)
        
        # First request should be allowed
        allowed, info = await limiter.check_rate_limit("test_key", "default")
        assert allowed
        assert info["remaining"] < info["limit"]
        
        await limiter.shutdown()
    
    @pytest.mark.asyncio
    async def test_rate_limiter_lru_eviction(self):
        """Test LRU eviction when max keys exceeded."""
        limiter = RateLimiter(max_keys=3, cleanup_interval=1)
        
        # Add more keys than max
        for i in range(5):
            await limiter.check_rate_limit(f"key_{i}", "default")
        
        stats = await limiter.get_stats()
        assert stats["total_keys"] <= 3  # Should be evicted
        
        await limiter.shutdown()
    
    @pytest.mark.asyncio
    async def test_rate_limiter_stats(self):
        """Test rate limiter statistics."""
        limiter = RateLimiter(max_keys=10)
        
        # Make some requests
        await limiter.check_rate_limit("test1", "default")
        await limiter.check_rate_limit("test2", "default")
        
        stats = await limiter.get_stats()
        assert stats["total_keys"] == 2
        assert stats["max_keys"] == 10
        assert not stats["is_shutdown"]
        
        await limiter.shutdown()


class TestEnhancedDecorators:
    """Test enhanced error handling decorators."""
    
    @pytest.mark.asyncio
    async def test_safe_async_operation_success(self):
        """Test successful operation with safe decorator."""
        
        @safe_async_operation("test_component", log_result=True)
        async def test_function(value):
            return value * 2
        
        result = await test_function(5)
        assert result == 10
    
    @pytest.mark.asyncio
    async def test_safe_async_operation_with_fallback(self):
        """Test operation with error and fallback."""
        
        @safe_async_operation(
            "test_component", 
            fallback_value="fallback",
            error_severity=ErrorSeverity.LOW
        )
        async def failing_function():
            raise ValueError("Test error")
        
        result = await failing_function()
        assert result == "fallback"
    
    @pytest.mark.asyncio
    async def test_performance_monitor(self):
        """Test performance monitoring decorator."""
        
        @performance_monitor("test_component", warn_threshold=0.1)
        async def slow_function():
            await asyncio.sleep(0.05)  # 50ms
            return "done"
        
        result = await slow_function()
        assert result == "done"


class TestMemoryManagerWithPooling:
    """Test memory manager with connection pooling."""
    
    @pytest.mark.asyncio
    async def test_memory_manager_initialization(self):
        """Test memory manager with connection pooling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "memory_test.db")
            manager = MemoryManager(db_path)
            
            await manager.initialize()
            
            # Test basic operations
            await manager.save_session("test_session", [{"role": "user", "content": "test"}])
            messages = await manager.load_session("test_session")
            
            assert len(messages) == 1
            assert messages[0]["content"] == "test"
    
    @pytest.mark.asyncio
    async def test_memory_manager_stats(self):
        """Test memory manager statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "stats_test.db")
            manager = MemoryManager(db_path)
            
            await manager.initialize()
            
            # Add some test data
            await manager.save_session("session1", [{"role": "user", "content": "test1"}])
            await manager.save_session("session2", [{"role": "user", "content": "test2"}])
            
            stats = await manager.get_session_stats()
            assert stats["sessions"] == 2
            
            # Cleanup connections
            await cleanup_database_pool()


class TestIntegrationScenarios:
    """Test complex integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_concurrent_database_operations(self):
        """Test concurrent database operations with pooling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "concurrent_test.db")
            manager = MemoryManager(db_path)
            await manager.initialize()
            
            # Run concurrent operations
            async def save_session(session_id):
                await manager.save_session(
                    f"session_{session_id}", 
                    [{"role": "user", "content": f"message_{session_id}"}]
                )
            
            # Create 10 concurrent sessions
            tasks = [save_session(i) for i in range(10)]
            await asyncio.gather(*tasks)
            
            # Verify all sessions were saved
            stats = await manager.get_session_stats()
            assert stats["sessions"] == 10
            
            await cleanup_database_pool()
    
    @pytest.mark.asyncio
    async def test_full_cleanup_cycle(self):
        """Test complete cleanup of all global resources."""
        # Initialize all components
        await get_http_client()
        await get_database_pool("test.db")
        
        # Cleanup everything
        await cleanup_http_client()
        await cleanup_database_pool()
        await cleanup_rate_limiter()
        
        # Should not raise any exceptions
        assert True  # If we reach here, cleanup worked


class TestErrorScenarios:
    """Test error handling and recovery scenarios."""
    
    @pytest.mark.asyncio
    async def test_database_connection_failure_recovery(self):
        """Test recovery from database connection failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "failure_test.db")
            pool = DatabasePool(db_path, pool_size=2)
            
            # Test that invalid operations don't break the pool
            try:
                async with pool.get_connection() as conn:
                    await conn.execute("INVALID SQL SYNTAX")
            except Exception:
                pass  # Expected to fail
            
            # Pool should still work for valid operations
            async with pool.get_connection() as conn:
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                assert result[0] == 1
            
            await pool.close()
    
    @pytest.mark.asyncio
    async def test_rate_limiter_under_load(self):
        """Test rate limiter behavior under high load."""
        limiter = RateLimiter(max_keys=10, cleanup_interval=1)
        
        # Generate many requests quickly
        tasks = []
        for i in range(50):
            task = limiter.check_rate_limit(f"key_{i % 5}", "default")
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # Should handle all requests without errors
        assert len(results) == 50
        assert all(isinstance(result, tuple) for result in results)
        
        await limiter.shutdown()


# Performance benchmarks
@pytest.mark.performance
class TestPerformance:
    """Performance tests for optimized components."""
    
    @pytest.mark.asyncio
    async def test_connection_pool_performance(self):
        """Benchmark connection pool performance."""
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "perf_test.db")
            pool = DatabasePool(db_path, pool_size=5)
            
            start_time = time.time()
            
            # Perform 100 database operations
            async def db_operation(i):
                async with pool.get_connection() as conn:
                    cursor = await conn.execute("SELECT ?", (i,))
                    await cursor.fetchone()
            
            tasks = [db_operation(i) for i in range(100)]
            await asyncio.gather(*tasks)
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Should complete 100 operations in reasonable time
            assert duration < 5.0  # Less than 5 seconds
            
            await pool.close()
    
    @pytest.mark.asyncio
    async def test_rate_limiter_performance(self):
        """Benchmark rate limiter performance."""
        import time
        
        limiter = RateLimiter(max_keys=1000, cleanup_interval=60)
        
        start_time = time.time()
        
        # Perform 1000 rate limit checks
        tasks = []
        for i in range(1000):
            task = limiter.check_rate_limit(f"key_{i % 100}", "default")
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Should handle 1000 checks quickly
        assert duration < 2.0  # Less than 2 seconds
        
        await limiter.shutdown()


if __name__ == "__main__":
    # Run a quick smoke test
    async def smoke_test():
        print("🧪 Running SAM Framework improvements smoke test...")
        
        # Test HTTP client
        client = await get_http_client()
        session = await client.get_session()
        assert session is not None
        print("✅ HTTP client: OK")
        
        # Test database pool
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "smoke_test.db")
            pool = DatabasePool(db_path)
            async with pool.get_connection() as conn:
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                assert result[0] == 1
            await pool.close()
        print("✅ Database pool: OK")
        
        # Test rate limiter
        limiter = RateLimiter(max_keys=10)
        allowed, info = await limiter.check_rate_limit("test", "default")
        assert allowed
        await limiter.shutdown()
        print("✅ Rate limiter: OK")
        
        # Cleanup
        await cleanup_http_client()
        await cleanup_database_pool()
        await cleanup_rate_limiter()
        
        print("🎉 All improvements working correctly!")
    
    asyncio.run(smoke_test())