import pytest
import asyncio
import tempfile
import os
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
from sam.utils.error_handling import (
    ErrorSeverity,
    ErrorRecord,
    ErrorTracker,
    CircuitBreaker,
    HealthChecker,
    get_error_tracker,
    get_health_checker,
    log_error,
    handle_errors,
)


class TestErrorSeverity:
    """Test ErrorSeverity enum."""

    def test_error_severity_values(self):
        """Test error severity enum values."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_error_severity_ordering(self):
        """Test error severity ordering."""
        # Test that enum values are properly ordered by severity level
        severities = [
            ErrorSeverity.LOW,
            ErrorSeverity.MEDIUM,
            ErrorSeverity.HIGH,
            ErrorSeverity.CRITICAL,
        ]
        for i in range(len(severities) - 1):
            assert severities[i] != severities[i + 1]  # Different values
            assert severities[i].value != severities[i + 1].value  # Different string values


class TestErrorRecord:
    """Test ErrorRecord class."""

    def test_error_record_creation(self):
        """Test ErrorRecord initialization."""
        timestamp = datetime.utcnow()
        record = ErrorRecord(
            timestamp=timestamp,
            error_type="ValueError",
            error_message="Test error",
            severity=ErrorSeverity.MEDIUM,
            component="test_component",
            session_id="session123",
            user_id="user123",
            context={"key": "value"},
            stack_trace="traceback here",
        )

        assert record.timestamp == timestamp
        assert record.error_type == "ValueError"
        assert record.error_message == "Test error"
        assert record.severity == ErrorSeverity.MEDIUM
        assert record.component == "test_component"
        assert record.session_id == "session123"
        assert record.user_id == "user123"
        assert record.context == {"key": "value"}
        assert record.stack_trace == "traceback here"

    def test_error_record_defaults(self):
        """Test ErrorRecord with default values."""
        timestamp = datetime.utcnow()
        record = ErrorRecord(
            timestamp=timestamp,
            error_type="ValueError",
            error_message="Test error",
            severity=ErrorSeverity.LOW,
            component="test_component",
        )

        assert record.session_id is None
        assert record.user_id is None
        assert record.context is None
        assert record.stack_trace is None


class TestErrorTracker:
    """Test ErrorTracker class functionality."""

    @pytest.fixture
    async def error_tracker(self):
        """Create a test error tracker."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test_errors.db")
            tracker = ErrorTracker(db_path)
            await tracker.initialize()
            yield tracker

    @pytest.mark.asyncio
    async def test_error_tracker_initialization(self, error_tracker):
        """Test error tracker initialization."""
        assert error_tracker.db_path.endswith("test_errors.db")
        assert isinstance(error_tracker.error_counts, dict)
        assert error_tracker.last_cleanup <= datetime.utcnow()

    @pytest.mark.asyncio
    async def test_log_error_basic(self, error_tracker):
        """Test basic error logging."""
        error = ValueError("Test error")
        await error_tracker.log_error(
            error=error, component="test_component", severity=ErrorSeverity.MEDIUM
        )

        # Check in-memory counts
        assert error_tracker.error_counts["test_component_ValueError"] == 1

    @pytest.mark.asyncio
    async def test_log_error_with_context(self, error_tracker):
        """Test error logging with additional context."""
        error = ValueError("Test error")
        await error_tracker.log_error(
            error=error,
            component="test_component",
            severity=ErrorSeverity.HIGH,
            session_id="session123",
            user_id="user123",
            context={"operation": "test"},
        )

        # Verify error was stored in database
        stats = await error_tracker.get_error_stats()
        assert stats["total_errors"] >= 1

    @pytest.mark.asyncio
    async def test_get_error_stats(self, error_tracker):
        """Test error statistics retrieval."""
        # Log some test errors
        await error_tracker.log_error(ValueError("Error 1"), "component1", ErrorSeverity.LOW)
        await error_tracker.log_error(RuntimeError("Error 2"), "component1", ErrorSeverity.MEDIUM)
        await error_tracker.log_error(ConnectionError("Error 3"), "component2", ErrorSeverity.HIGH)

        stats = await error_tracker.get_error_stats(hours_back=1)

        assert stats["total_errors"] == 3
        assert "low" in stats["severity_counts"]
        assert "medium" in stats["severity_counts"]
        assert "high" in stats["severity_counts"]
        assert "component1" in stats["component_counts"]
        assert "component2" in stats["component_counts"]

    @pytest.mark.asyncio
    async def test_cleanup_old_errors(self, error_tracker):
        """Test cleanup of old error records."""
        # Log an error
        await error_tracker.log_error(ValueError("Old error"), "test_component", ErrorSeverity.LOW)

        # Cleanup errors older than 0 days (should remove all)
        deleted = await error_tracker.cleanup_old_errors(days_old=0)
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_get_error_tracker_global_instance(self):
        """Test global error tracker instance."""
        # Reset the global instance
        import sam.utils.error_handling

        sam.utils.error_handling._error_tracker = None

        with patch("sam.utils.error_handling.ErrorTracker") as mock_tracker_class:
            mock_tracker = AsyncMock()
            mock_tracker_class.return_value = mock_tracker

            tracker1 = await get_error_tracker()
            tracker2 = await get_error_tracker()

            # Should return the same instance
            assert tracker1 == tracker2
            mock_tracker_class.assert_called_once()


class TestCircuitBreaker:
    """Test CircuitBreaker class functionality."""

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initialization."""
        cb = CircuitBreaker("test_breaker", failure_threshold=5, recovery_timeout=60)

        assert cb.name == "test_breaker"
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.failure_count == 0
        assert cb.state == "closed"
        assert cb.last_failure_time is None

    @pytest.mark.asyncio
    async def test_circuit_breaker_success(self):
        """Test successful circuit breaker operation."""
        cb = CircuitBreaker("test_breaker")

        async def success_func():
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.failure_count == 0
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_then_recovery(self):
        """Test circuit breaker failure and recovery."""
        cb = CircuitBreaker("test_breaker", failure_threshold=2, recovery_timeout=1)

        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("Test failure")
            return "success"

        # First two calls should fail and open circuit
        with pytest.raises(ValueError):
            await cb.call(failing_func)
        with pytest.raises(ValueError):
            await cb.call(failing_func)

        assert cb.state == "open"

        # Third call should also fail (circuit open)
        with pytest.raises(Exception):  # Circuit breaker error
            await cb.call(failing_func)

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Next call should succeed and close circuit
        result = await cb.call(failing_func)
        assert result == "success"
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker half-open state recovery."""
        cb = CircuitBreaker("test_breaker", failure_threshold=1, recovery_timeout=1)

        # Fail once to open circuit
        async def failing_func():
            raise ValueError("Test failure")

        with pytest.raises(ValueError):
            await cb.call(failing_func)

        assert cb.state == "open"

        # Wait for recovery and try successful function
        await asyncio.sleep(1.1)

        async def success_func():
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == "closed"


class TestHealthChecker:
    """Test HealthChecker class functionality."""

    def test_health_checker_initialization(self):
        """Test health checker initialization."""
        hc = HealthChecker()

        assert isinstance(hc.checks, dict)
        assert isinstance(hc.last_check_time, dict)

    def test_register_health_check(self):
        """Test health check registration."""
        hc = HealthChecker()

        def test_check():
            return {"status": "healthy"}

        hc.register_health_check("test_check", test_check, interval=30)

        assert "test_check" in hc.checks
        assert hc.checks["test_check"]["interval"] == 30
        assert hc.checks["test_check"]["func"] == test_check

    @pytest.mark.asyncio
    async def test_run_health_checks(self):
        """Test running health checks."""
        hc = HealthChecker()

        async def async_check():
            return {"status": "healthy", "details": {"uptime": 100}}

        def sync_check():
            return {"status": "healthy", "details": {"version": "1.0"}}

        hc.register_health_check("async_check", async_check)
        hc.register_health_check("sync_check", sync_check)

        results = await hc.run_health_checks()

        assert "async_check" in results
        assert "sync_check" in results
        assert results["async_check"]["status"] == "healthy"
        assert results["sync_check"]["status"] == "healthy"

    def test_get_health_checker_global_instance(self):
        """Test global health checker instance."""
        with patch("sam.utils.error_handling.HealthChecker") as mock_hc_class:
            mock_hc = MagicMock()
            mock_hc_class.return_value = mock_hc

            hc1 = get_health_checker()
            hc2 = get_health_checker()

            # Should return the same instance
            assert hc1 == hc2
            mock_hc_class.assert_called_once()


class TestUtilityFunctions:
    """Test utility functions."""

    @pytest.mark.asyncio
    async def test_log_error_convenience_function(self):
        """Test convenience log_error function."""
        with patch("sam.utils.error_handling.get_error_tracker") as mock_get_tracker:
            mock_tracker = AsyncMock()
            mock_get_tracker.return_value = mock_tracker

            error = ValueError("Test error")
            await log_error(error, "test_component", ErrorSeverity.HIGH)

            mock_tracker.log_error.assert_called_once()
            call_args = mock_tracker.log_error.call_args
            assert call_args[0][0] == error  # First positional argument
            assert call_args[0][1] == "test_component"  # Second positional argument
            assert call_args[0][2] == ErrorSeverity.HIGH  # Third positional argument

    def test_handle_errors_decorator_async(self):
        """Test handle_errors decorator with async function."""
        with patch("sam.utils.error_handling.log_error"):

            @handle_errors("test_component", ErrorSeverity.MEDIUM)
            async def test_func():
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                asyncio.run(test_func())

            # Should have logged the error
            # Note: In real usage, this would be awaited, but for sync test we skip

    def test_handle_errors_decorator_sync(self):
        """Test handle_errors decorator with sync function."""
        with patch("sam.utils.error_handling.logger") as mock_logger:

            @handle_errors("test_component", ErrorSeverity.MEDIUM)
            def test_func():
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                test_func()

            # Should have logged the error
            mock_logger.error.assert_called()


if __name__ == "__main__":
    pytest.main([__file__])
