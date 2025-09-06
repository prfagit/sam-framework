import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock
from sam.utils.enhanced_decorators import (
    safe_async_operation,
    performance_monitor,
    _should_retry,
    _sanitize_args,
    _sanitize_result,
)
from sam.utils.error_handling import ErrorSeverity


class TestSafeAsyncOperation:
    """Test safe async operation decorator functionality."""

    @pytest.mark.asyncio
    async def test_safe_operation_success(self):
        """Test successful operation with logging."""
        with patch("sam.utils.enhanced_decorators.logger") as mock_logger:

            @safe_async_operation("test_component", log_args=True, log_result=True)
            async def test_func(x, y):
                return x + y

            result = await test_func(2, 3)

            assert result == 5

            # Check logging calls
            debug_calls = [call for call in mock_logger.debug.call_args_list if call]
            assert len(debug_calls) >= 2  # Entry and completion logs

    @pytest.mark.asyncio
    async def test_safe_operation_with_retries(self):
        """Test operation with retries on failure."""
        call_count = 0

        @safe_async_operation("test_component", max_retries=2, retry_delay=0.1)
        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return {"success": True}

        with patch("asyncio.sleep") as mock_sleep:
            result = await test_func()

            assert result == {"success": True}
            assert call_count == 3
            assert mock_sleep.call_count == 2  # Should sleep twice

    @pytest.mark.asyncio
    async def test_safe_operation_fallback_value(self):
        """Test operation with fallback value on error."""

        @safe_async_operation("test_component", fallback_value="default")
        async def test_func():
            raise Exception("Test error")

        result = await test_func()

        assert result == "default"

    @pytest.mark.asyncio
    async def test_safe_operation_error_tracking(self):
        """Test error tracking integration."""
        with patch("sam.utils.enhanced_decorators.get_error_tracker") as mock_get_tracker:
            mock_tracker = AsyncMock()
            mock_get_tracker.return_value = mock_tracker

            @safe_async_operation("test_component", error_severity=ErrorSeverity.HIGH)
            async def test_func():
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                await test_func()

            # Verify error was tracked
            mock_tracker.log_error.assert_called_once()
            call_args = mock_tracker.log_error.call_args
            assert call_args[1]["severity"] == ErrorSeverity.HIGH
            assert call_args[1]["component"] == "test_component"

    @pytest.mark.asyncio
    async def test_safe_operation_no_retry_errors(self):
        """Test that certain errors don't trigger retries."""
        call_count = 0

        @safe_async_operation("test_component", max_retries=2)
        async def test_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")  # Should not retry

        with pytest.raises(ValueError):
            await test_func()

        assert call_count == 1  # Should not retry

    @pytest.mark.asyncio
    async def test_safe_operation_sync_function(self):
        """Test decorator works with synchronous functions."""

        @safe_async_operation("test_component")
        def test_func(x):
            return x * 2

        result = await test_func(5)

        assert result == 10


class TestPerformanceMonitor:
    """Test performance monitor decorator functionality."""

    @pytest.mark.asyncio
    async def test_performance_normal_operation(self):
        """Test normal performance logging."""
        with patch("sam.utils.enhanced_decorators.logger") as mock_logger:

            @performance_monitor("test_component", warn_threshold=1.0)
            async def test_func():
                await asyncio.sleep(0.01)
                return "result"

            result = await test_func()

            assert result == "result"

            # Should log at debug level for normal performance
            mock_logger.debug.assert_called()
            mock_logger.warning.assert_not_called()
            mock_logger.critical.assert_not_called()

    @pytest.mark.asyncio
    async def test_performance_warning_threshold(self):
        """Test warning threshold logging."""
        with patch("sam.utils.enhanced_decorators.logger") as mock_logger:

            @performance_monitor("test_component", warn_threshold=0.01, critical_threshold=1.0)
            async def test_func():
                await asyncio.sleep(0.1)  # Exceed warning threshold
                return "result"

            result = await test_func()

            assert result == "result"

            # Should log warning
            mock_logger.warning.assert_called()
            warning_call = str(mock_logger.warning.call_args)
            assert "slow" in warning_call

    @pytest.mark.asyncio
    async def test_performance_critical_threshold(self):
        """Test critical threshold logging."""
        with patch("sam.utils.enhanced_decorators.logger") as mock_logger:

            @performance_monitor("test_component", warn_threshold=0.01, critical_threshold=0.01)
            async def test_func():
                await asyncio.sleep(0.1)  # Exceed critical threshold
                return "result"

            result = await test_func()

            assert result == "result"

            # Should log critical
            mock_logger.critical.assert_called()
            critical_call = str(mock_logger.critical.call_args)
            assert "CRITICAL SLOW" in critical_call

    @pytest.mark.asyncio
    async def test_performance_sync_function(self):
        """Test performance monitoring with synchronous functions."""
        with patch("sam.utils.enhanced_decorators.logger") as mock_logger:

            @performance_monitor("test_component")
            def test_func():
                time.sleep(0.01)
                return "sync_result"

            result = await test_func()

            assert result == "sync_result"
            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_performance_error_logging(self):
        """Test error logging in performance monitor."""
        with patch("sam.utils.enhanced_decorators.logger") as mock_logger:

            @performance_monitor("test_component")
            async def test_func():
                await asyncio.sleep(0.01)
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                await test_func()

            # Should log error with timing
            mock_logger.error.assert_called()
            error_call = str(mock_logger.error.call_args)
            assert "failed after" in error_call


class TestCircuitBreakerEnhanced:
    """Test enhanced circuit breaker decorator functionality."""

    @pytest.mark.skip(reason="Circuit breaker implementation incomplete in codebase")
    @pytest.mark.asyncio
    async def test_circuit_breaker_success(self):
        """Test successful circuit breaker operation."""
        pass

    @pytest.mark.skip(reason="Circuit breaker implementation incomplete in codebase")
    @pytest.mark.asyncio
    async def test_circuit_breaker_custom_config(self):
        """Test circuit breaker with custom configuration."""
        pass


class TestHelperFunctions:
    """Test helper functions used by decorators."""

    def test_should_retry_connection_error(self):
        """Test retry decision for connection errors."""
        error = ConnectionError("Connection failed")
        assert _should_retry(error) is True

    def test_should_retry_timeout_error(self):
        """Test retry decision for timeout errors."""
        error = TimeoutError("Request timed out")
        assert _should_retry(error) is True

    def test_should_retry_value_error(self):
        """Test retry decision for value errors."""
        error = ValueError("Invalid input")
        assert _should_retry(error) is False

    def test_should_retry_type_error(self):
        """Test retry decision for type errors."""
        error = TypeError("Wrong type")
        assert _should_retry(error) is False

    def test_should_retry_key_error(self):
        """Test retry decision for key errors."""
        error = KeyError("Missing key")
        assert _should_retry(error) is False

    def test_should_retry_network_message(self):
        """Test retry decision based on error message."""
        error = Exception("Network connection timeout occurred")
        assert _should_retry(error) is True

    def test_should_retry_rate_limit_message(self):
        """Test retry decision for rate limit errors."""
        error = Exception("Rate limit exceeded")
        assert _should_retry(error) is True

    def test_should_retry_server_error_message(self):
        """Test retry decision for server errors."""
        error = Exception("Internal server error 500")
        assert _should_retry(error) is True

    def test_should_retry_validation_error(self):
        """Test no retry for validation errors."""
        error = Exception("Invalid input format")
        assert _should_retry(error) is False

    def test_sanitize_args_basic(self):
        """Test basic argument sanitization."""
        args = (1, "test", {"key": "value"})
        kwargs = {"name": "John", "password": "secret123"}

        result = _sanitize_args(args, kwargs)

        assert "args" in result
        assert "kwargs" in result
        assert result["kwargs"]["password"] == "***REDACTED***"
        assert result["kwargs"]["name"] == "John"

    def test_sanitize_args_sensitive_keys(self):
        """Test sanitization of various sensitive keys."""
        kwargs = {
            "api_key": "secret",
            "private_key": "private",
            "token": "token123",
            "auth": "auth_data",
            "wallet": "wallet_data",
        }

        result = _sanitize_args((), kwargs)

        for key in kwargs.keys():
            assert result["kwargs"][key] == "***REDACTED***"

    def test_sanitize_args_long_strings(self):
        """Test truncation of long strings."""
        long_string = "a" * 150
        kwargs = {"data": long_string}

        result = _sanitize_args((), kwargs)

        assert len(result["kwargs"]["data"]) <= 105  # 100 chars + "..."
        assert result["kwargs"]["data"].endswith("...")

    def test_sanitize_result_dict_with_sensitive_data(self):
        """Test result sanitization for sensitive data."""
        result = {"private_key": "secret", "token": "token123", "normal": "value"}

        sanitized = _sanitize_result(result)

        assert isinstance(sanitized, str)
        assert "potentially sensitive" in sanitized

    def test_sanitize_result_normal_dict(self):
        """Test result sanitization for normal data."""
        result = {"name": "John", "age": 30, "data": "some_value"}

        sanitized = _sanitize_result(result)

        assert isinstance(sanitized, dict)
        assert "name" in sanitized
        assert "age" in sanitized

    def test_sanitize_result_long_string(self):
        """Test result sanitization for long strings."""
        long_string = "a" * 150

        sanitized = _sanitize_result(long_string)

        assert len(sanitized) <= 103  # 100 chars + "..."
        assert sanitized.endswith("...")

    def test_sanitize_result_list(self):
        """Test result sanitization for lists."""
        long_list = list(range(10))

        sanitized = _sanitize_result(long_list)

        assert isinstance(sanitized, str)
        assert "10 items" in sanitized

    def test_sanitize_result_tuple(self):
        """Test result sanitization for tuples."""
        long_tuple = tuple(range(8))

        sanitized = _sanitize_result(long_tuple)

        assert isinstance(sanitized, str)
        assert "8 items" in sanitized


if __name__ == "__main__":
    pytest.main([__file__])
