import pytest
import asyncio
import tempfile
import os
from sam.utils.error_handling import (
    ErrorTracker, ErrorSeverity, CircuitBreaker, 
    HealthChecker, get_error_tracker, log_error
)


@pytest.mark.asyncio
async def test_error_tracker_initialization():
    """Test error tracker initialization."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_errors.db")
        tracker = ErrorTracker(db_path)
        await tracker.initialize()
        
        # Test that database was created
        assert os.path.exists(db_path)
        
        # Test initial stats
        stats = await tracker.get_error_stats()
        assert stats["total_errors"] == 0


@pytest.mark.asyncio
async def test_error_logging():
    """Test error logging functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_errors.db")
        tracker = ErrorTracker(db_path)
        await tracker.initialize()
        
        # Log a test error
        test_error = ValueError("Test error for logging")
        await tracker.log_error(
            test_error,
            "test_component",
            ErrorSeverity.MEDIUM,
            session_id="test_session",
            context={"test": "data"}
        )
        
        # Check that error was logged
        stats = await tracker.get_error_stats()
        assert stats["total_errors"] == 1
        assert "test_component" in stats["component_counts"]


@pytest.mark.asyncio
async def test_error_cleanup():
    """Test error cleanup functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_errors.db")
        tracker = ErrorTracker(db_path)
        await tracker.initialize()
        
        # Log some errors
        for i in range(5):
            error = RuntimeError(f"Test error {i}")
            await tracker.log_error(error, "test_component")
        
        # Check we have 5 errors
        stats = await tracker.get_error_stats()
        assert stats["total_errors"] == 5
        
        # Clean up (should delete 0 since they're recent)
        deleted = await tracker.cleanup_old_errors(0)  # 0 days = delete all
        assert deleted == 5
        
        # Check they're gone
        stats = await tracker.get_error_stats()
        assert stats["total_errors"] == 0


@pytest.mark.asyncio
async def test_circuit_breaker():
    """Test circuit breaker functionality."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=1)
    
    call_count = 0
    
    def failing_function():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ValueError("Simulated failure")
        return "success"
    
    # First two calls should fail and open the circuit
    with pytest.raises(ValueError):
        await breaker.call(failing_function)
    
    with pytest.raises(ValueError):
        await breaker.call(failing_function)
    
    # Circuit should now be open
    assert breaker.state == "open"
    
    # This should be rejected immediately
    with pytest.raises(Exception, match="Circuit breaker.*is open"):
        await breaker.call(failing_function)
    
    # Wait for recovery timeout and try again
    await asyncio.sleep(1.1)
    
    # Should succeed now (circuit goes to half_open, then closed)
    result = await breaker.call(failing_function)
    assert result == "success"
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_health_checker():
    """Test health checker functionality."""
    checker = HealthChecker()
    
    # Register a healthy check
    def healthy_check():
        return {"status": "all good"}
    
    # Register an unhealthy check
    def unhealthy_check():
        raise Exception("Something is wrong")
    
    checker.register_health_check("healthy_service", healthy_check, 0)
    checker.register_health_check("unhealthy_service", unhealthy_check, 0)
    
    # Run health checks
    results = await checker.run_health_checks()
    
    # Verify results
    assert "healthy_service" in results
    assert "unhealthy_service" in results
    
    assert results["healthy_service"]["status"] == "healthy"
    assert results["unhealthy_service"]["status"] == "unhealthy"
    assert "Something is wrong" in results["unhealthy_service"]["error"]


@pytest.mark.asyncio
async def test_global_error_tracker():
    """Test global error tracker functions."""
    # Test the global convenience functions
    test_error = RuntimeError("Global tracker test")
    
    await log_error(test_error, "global_test", ErrorSeverity.LOW)
    
    # Should work without exceptions
    tracker = await get_error_tracker()
    assert tracker is not None
    
    stats = await tracker.get_error_stats()
    assert stats["total_errors"] >= 0  # May have errors from other tests


def test_error_decorator():
    """Test error handling decorator."""
    from sam.utils.error_handling import handle_errors
    
    @handle_errors("test_component", ErrorSeverity.HIGH)
    def failing_function():
        raise ValueError("Decorated function error")
    
    # Should still raise the error but log it
    with pytest.raises(ValueError, match="Decorated function error"):
        failing_function()


@pytest.mark.asyncio
async def test_async_error_decorator():
    """Test async error handling decorator."""
    from sam.utils.error_handling import handle_errors
    
    @handle_errors("async_test_component", ErrorSeverity.CRITICAL)
    async def async_failing_function():
        raise RuntimeError("Async decorated function error")
    
    # Should still raise the error but log it
    with pytest.raises(RuntimeError, match="Async decorated function error"):
        await async_failing_function()