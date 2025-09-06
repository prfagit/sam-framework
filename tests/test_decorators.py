import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock
from sam.utils.decorators import (
    rate_limit, retry_with_backoff, log_execution, validate_args
)
from sam.config.settings import Settings


class TestRateLimitDecorator:
    """Test rate limiting decorator functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_disabled(self):
        """Test that decorator passes through when rate limiting is disabled."""
        # Mock Settings to disable rate limiting
        with patch.object(Settings, 'RATE_LIMITING_ENABLED', False):
            call_count = 0

            @rate_limit("test")
            async def test_func(args):
                nonlocal call_count
                call_count += 1
                return {"success": True}

            # Call the function
            result = await test_func({"user_id": "test_user"})

            # Should execute without rate limiting
            assert result == {"success": True}
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self):
        """Test successful rate limit check."""
        with patch.object(Settings, 'RATE_LIMITING_ENABLED', True):
            with patch('sam.utils.decorators.check_rate_limit') as mock_check_rate_limit:
                # Mock successful rate limit check
                mock_check_rate_limit.return_value = (True, {
                    "remaining": 9,
                    "limit": 10,
                    "reset_time": 1234567890
                })

                call_count = 0

                @rate_limit("test")
                async def test_func(args):
                    nonlocal call_count
                    call_count += 1
                    return {"success": True}

                result = await test_func({"user_id": "test_user"})

                # Should execute and add rate limit info
                assert result["success"] is True
                assert "rate_limit_info" in result
                assert result["rate_limit_info"]["remaining"] == 9
                assert call_count == 1

                # Verify rate limit check was called
                mock_check_rate_limit.assert_called_once_with("test_user", "test")

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        """Test rate limit exceeded response."""
        with patch.object(Settings, 'RATE_LIMITING_ENABLED', True):
            with patch('sam.utils.decorators.check_rate_limit') as mock_check_rate_limit:
                # Mock rate limit exceeded
                mock_check_rate_limit.return_value = (False, {
                    "retry_after": 60,
                    "remaining": 0
                })

                call_count = 0

                @rate_limit("test")
                async def test_func(args):
                    nonlocal call_count
                    call_count += 1
                    return {"success": True}

                result = await test_func({"user_id": "test_user"})

                # Should return error without executing function
                assert "error" in result
                assert "Rate limit exceeded" in result["error"]
                assert call_count == 0  # Function should not be called

    @pytest.mark.asyncio
    async def test_rate_limit_identifier_extraction(self):
        """Test identifier extraction from different argument patterns."""
        with patch.object(Settings, 'RATE_LIMITING_ENABLED', True):
            with patch('sam.utils.decorators.check_rate_limit') as mock_check_rate_limit:
                mock_check_rate_limit.return_value = (True, {"remaining": 5})

                @rate_limit("test")
                async def test_func(args, **kwargs):
                    return {"success": True}

                # Test with user_id in kwargs
                await test_func({"data": "test"}, user_id="user123")
                mock_check_rate_limit.assert_called_with("user123", "test")

                # Test with public_key in kwargs
                mock_check_rate_limit.reset_mock()
                await test_func({"data": "test"}, public_key="pub123")
                mock_check_rate_limit.assert_called_with("pub123", "test")

                # Test with identifier in args dict
                mock_check_rate_limit.reset_mock()
                await test_func({"user_id": "arg123"})
                mock_check_rate_limit.assert_called_with("arg123", "test")

                # Test with custom identifier key
                mock_check_rate_limit.reset_mock()
                @rate_limit("test", identifier_key="custom_id")
                async def test_func2(args, **kwargs):
                    return {"success": True}

                await test_func2({"custom_id": "custom123"})
                mock_check_rate_limit.assert_called_with("custom123", "test")

    @pytest.mark.asyncio
    async def test_rate_limit_default_identifier(self):
        """Test default identifier when none found."""
        with patch.object(Settings, 'RATE_LIMITING_ENABLED', True):
            with patch('sam.utils.decorators.check_rate_limit') as mock_check_rate_limit:
                mock_check_rate_limit.return_value = (True, {"remaining": 5})

                @rate_limit("test")
                async def test_func(args):
                    return {"success": True}

                # Call without any identifiable args
                await test_func({})
                mock_check_rate_limit.assert_called_with("anonymous", "test")

    @pytest.mark.asyncio
    async def test_rate_limit_error_handling(self):
        """Test error handling in rate limiter."""
        with patch.object(Settings, 'RATE_LIMITING_ENABLED', True):
            with patch('sam.utils.decorators.check_rate_limit', side_effect=Exception("Rate limiter error")):
                call_count = 0

                @rate_limit("test")
                async def test_func(args):
                    nonlocal call_count
                    call_count += 1
                    return {"success": True}

                # Should execute function despite rate limiter error
                result = await test_func({"user_id": "test_user"})
                assert result == {"success": True}
                assert call_count == 1


class TestRetryWithBackoffDecorator:
    """Test retry with backoff decorator functionality."""

    @pytest.mark.asyncio
    async def test_retry_success_first_attempt(self):
        """Test successful execution on first attempt."""
        call_count = 0

        @retry_with_backoff(max_retries=3)
        async def test_func():
            nonlocal call_count
            call_count += 1
            return {"success": True}

        result = await test_func()

        assert result == {"success": True}
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_success_after_failures(self):
        """Test successful execution after some failures."""
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.1)
        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Attempt {call_count} failed")
            return {"success": True}

        with patch('asyncio.sleep') as mock_sleep:
            result = await test_func()

            assert result == {"success": True}
            assert call_count == 3
            # Should have slept twice (after attempt 1 and 2)
            assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """Test when all retries are exhausted."""
        call_count = 0

        @retry_with_backoff(max_retries=2, base_delay=0.1)
        async def test_func():
            nonlocal call_count
            call_count += 1
            raise Exception(f"Attempt {call_count} failed")

        with patch('asyncio.sleep') as mock_sleep:
            result = await test_func()

            assert "error" in result
            assert "Operation failed after 3 attempts" in result["error"]
            assert result["retry_attempts"] == 3
            assert call_count == 3
            # Should have slept twice
            assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_custom_parameters(self):
        """Test retry with custom parameters."""
        call_count = 0

        @retry_with_backoff(max_retries=1, base_delay=2.0, backoff_factor=3.0)
        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First attempt failed")
            return {"success": True}

        with patch('asyncio.sleep') as mock_sleep:
            result = await test_func()

            assert result == {"success": True}
            assert call_count == 2
            # Should have slept with base_delay * backoff_factor^0 = 2.0 * 1 = 2.0
            mock_sleep.assert_called_with(2.0)


class TestLogExecutionDecorator:
    """Test logging execution decorator functionality."""

    @pytest.mark.asyncio
    async def test_log_execution_basic(self):
        """Test basic execution logging."""
        with patch('sam.utils.decorators.logger') as mock_logger:
            @log_execution()
            async def test_func():
                return {"result": "success"}

            result = await test_func()

            assert result == {"result": "success"}

            # Check debug calls
            debug_calls = [call for call in mock_logger.debug.call_args_list]
            assert len(debug_calls) == 2  # Entry and completion
            assert "Executing" in str(debug_calls[0])
            assert "Completed" in str(debug_calls[1])

    @pytest.mark.asyncio
    async def test_log_execution_with_args(self):
        """Test execution logging with arguments included."""
        with patch('sam.utils.decorators.logger') as mock_logger:
            @log_execution(include_args=True)
            async def test_func(arg1, arg2=None):
                return {"result": arg1}

            result = await test_func("test_value", arg2="test2")

            assert result == {"result": "test_value"}

            # Check that args were logged
            debug_calls = [call for call in mock_logger.debug.call_args_list]
            args_call = str(debug_calls[0])
            assert "args=" in args_call
            assert "kwargs=" in args_call

    @pytest.mark.asyncio
    async def test_log_execution_with_result(self):
        """Test execution logging with result included."""
        with patch('sam.utils.decorators.logger') as mock_logger:
            @log_execution(include_result=True)
            async def test_func():
                return {"result": "success"}

            result = await test_func()

            # Check that result was logged
            debug_calls = [call for call in mock_logger.debug.call_args_list]
            completion_call = str(debug_calls[1])
            assert "success" in completion_call

    @pytest.mark.asyncio
    async def test_log_execution_with_exception(self):
        """Test execution logging when exception occurs."""
        with patch('sam.utils.decorators.logger') as mock_logger:
            @log_execution()
            async def test_func():
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                await test_func()

            # Check that error was logged
            mock_logger.error.assert_called_once()
            error_call = str(mock_logger.error.call_args)
            assert "Failed" in error_call
            assert "Test error" in error_call

    @pytest.mark.asyncio
    async def test_log_execution_timing(self):
        """Test that execution timing is logged."""
        with patch('sam.utils.decorators.logger') as mock_logger:
            @log_execution()
            async def test_func():
                await asyncio.sleep(0.01)  # Small delay
                return {"result": "success"}

            result = await test_func()

            # Check that timing was logged
            debug_calls = [call for call in mock_logger.debug.call_args_list]
            completion_call = str(debug_calls[1])
            assert "s" in completion_call  # Timing format includes seconds


class TestValidateArgsDecorator:
    """Test argument validation decorator functionality."""

    @pytest.mark.asyncio
    async def test_validate_args_success(self):
        """Test successful argument validation."""
        def validator(value):
            if not isinstance(value, str):
                raise ValueError("Must be string")
            if len(value) < 3:
                raise ValueError("Must be at least 3 characters")
            return value

        @validate_args(name=validator)
        async def test_func(name, age):
            return {"name": name, "age": age}

        result = await test_func(name="John", age=25)

        assert result == {"name": "John", "age": 25}

    @pytest.mark.asyncio
    async def test_validate_args_failure(self):
        """Test argument validation failure."""
        def validator(value):
            if len(value) < 3:
                raise ValueError("Must be at least 3 characters")

        @validate_args(name=validator)
        async def test_func(name):
            return {"name": name}

        result = await test_func(name="A")  # Too short

        assert "error" in result
        assert "Validation failed for name" in result["error"]
        assert "at least 3 characters" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_args_dict_first_arg(self):
        """Test validation when first argument is a dict."""
        def validator(value):
            if not isinstance(value, int) or value <= 0:
                raise ValueError("Must be positive integer")

        @validate_args(amount=validator)
        async def test_func(args_dict):
            return {"amount": args_dict["amount"]}

        # Valid case
        result = await test_func({"amount": 100})
        assert result == {"amount": 100}

        # Invalid case
        result = await test_func({"amount": -5})
        assert "error" in result
        assert "Validation failed for amount" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_args_multiple_validators(self):
        """Test multiple validators on different arguments."""
        def name_validator(value):
            if not value:
                raise ValueError("Name cannot be empty")

        def age_validator(value):
            if value < 18:
                raise ValueError("Must be 18 or older")

        @validate_args(name=name_validator, age=age_validator)
        async def test_func(name, age):
            return {"name": name, "age": age}

        # Valid case
        result = await test_func(name="John", age=25)
        assert result == {"name": "John", "age": 25}

        # Invalid name
        result = await test_func(name="", age=25)
        assert "error" in result
        assert "name" in result["error"]

        # Invalid age
        result = await test_func(name="John", age=16)
        assert "error" in result
        assert "age" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_args_validator_exception(self):
        """Test handling of exceptions in validators."""
        def failing_validator(value):
            raise RuntimeError("Unexpected validator error")

        @validate_args(name=failing_validator)
        async def test_func(name):
            return {"name": name}

        result = await test_func(name="test")

        assert "error" in result
        assert "Validation failed for name" in result["error"]
        assert "Unexpected validator error" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__])
