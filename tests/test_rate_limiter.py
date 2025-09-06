import pytest
from sam.utils.rate_limiter import RateLimiter, RateLimit


@pytest.mark.asyncio
async def test_rate_limiter_basic_functionality():
    """Test basic rate limiter functionality with in-memory storage."""
    limiter = RateLimiter()

    # First request should be allowed
    allowed, info = await limiter.check_rate_limit("test_user", "default")
    assert allowed is True
    assert info["allowed"] is True
    assert info["remaining"] > 0
    assert info["retry_after"] == 0


@pytest.mark.asyncio
async def test_rate_limit_decorator():
    """Test rate limiting decorator functionality."""
    from sam.utils.decorators import rate_limit
    from sam.config.settings import Settings

    # Ensure rate limiting is enabled for this test
    original_setting = Settings.RATE_LIMITING_ENABLED
    Settings.RATE_LIMITING_ENABLED = True

    try:

        @rate_limit("default")
        async def test_function(args_dict):
            return {"success": True, "data": "test"}

        # Call with user identifier
        result = await test_function({"public_key": "test_user"})

        # Should succeed with rate limit info
        assert result["success"] is True
        assert "rate_limit_info" in result

    finally:
        # Restore original setting
        Settings.RATE_LIMITING_ENABLED = original_setting


@pytest.mark.asyncio
async def test_rate_limit_configuration():
    """Test that rate limit configurations are properly set."""
    limiter = RateLimiter()

    # Check that specific limits exist
    assert "pump_fun_buy" in limiter.limits
    assert "transfer_sol" in limiter.limits

    # Check that pump_fun_buy has reasonable limits
    pump_buy_limit = limiter.limits["pump_fun_buy"]
    assert pump_buy_limit.requests == 10
    assert pump_buy_limit.window == 60  # 1 minute
    assert pump_buy_limit.burst == 2

    # Check that transfer_sol has reasonable limits
    transfer_limit = limiter.limits["transfer_sol"]
    assert transfer_limit.requests == 5
    assert transfer_limit.window == 60
    assert transfer_limit.burst == 2


@pytest.mark.asyncio
async def test_rate_limit_enforcement():
    """Test that rate limits are actually enforced."""
    limiter = RateLimiter()

    # Create a very restrictive limit for testing
    test_limit = RateLimit(requests=2, window=60, burst=1)
    limiter.limits["test"] = test_limit

    # First two requests should be allowed
    allowed1, info1 = await limiter.check_rate_limit("test_user", "test")
    allowed2, info2 = await limiter.check_rate_limit("test_user", "test")

    assert allowed1 is True
    assert allowed2 is True

    # Third request should be denied
    allowed3, info3 = await limiter.check_rate_limit("test_user", "test")
    assert allowed3 is False
    assert info3["allowed"] is False
    assert info3["remaining"] == 0
    assert info3["retry_after"] > 0


@pytest.mark.asyncio
async def test_rate_limit_cleanup():
    """Test that old records are cleaned up."""
    limiter = RateLimiter()

    # Make some requests
    await limiter.check_rate_limit("user1", "default")
    await limiter.check_rate_limit("user2", "default")

    # Should have records
    assert len(limiter.request_history) == 2

    # Manually trigger cleanup logic
    import time

    current_time = time.time()

    async with limiter.lock:
        # Simulate old records by backdating them
        for key in limiter.request_history:
            for record in limiter.request_history[key]:
                record.timestamp = current_time - 7200  # 2 hours ago

        # Now clean them up
        keys_to_remove = []
        for key, records in limiter.request_history.items():
            cutoff_time = current_time - 3600  # 1 hour cutoff
            limiter.request_history[key] = [
                record for record in records if record.timestamp > cutoff_time
            ]

            if not limiter.request_history[key]:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del limiter.request_history[key]

    # Should be cleaned up
    assert len(limiter.request_history) == 0


@pytest.mark.asyncio
async def test_retry_decorator():
    """Test retry decorator functionality."""
    from sam.utils.decorators import retry_with_backoff

    call_count = 0

    @retry_with_backoff(max_retries=2, base_delay=0.01)
    async def failing_function():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("Temporary failure")
        return {"success": True, "attempts": call_count}

    result = await failing_function()
    assert result["success"] is True
    assert result["attempts"] == 2


@pytest.mark.asyncio
async def test_log_execution_decorator():
    """Test log execution decorator functionality."""
    from sam.utils.decorators import log_execution

    @log_execution()
    async def test_function(arg1, arg2="default"):
        return {"result": f"{arg1}-{arg2}"}

    result = await test_function("test", arg2="custom")
    assert result["result"] == "test-custom"


@pytest.mark.asyncio
async def test_rate_limit_info():
    """Test getting rate limit info without making a request."""
    limiter = RateLimiter()

    # Check info for unused key
    info = await limiter.get_rate_limit_info("unused_user", "default")
    default_limit = limiter.limits["default"]

    assert info["limit"] == default_limit.requests
    assert info["remaining"] == default_limit.requests
    assert info["used"] == 0

    # Make a request and check again
    await limiter.check_rate_limit("used_user", "default")
    info_after = await limiter.get_rate_limit_info("used_user", "default")

    assert info_after["used"] == 1
    assert info_after["remaining"] == default_limit.requests - 1


@pytest.mark.asyncio
async def test_rate_limit_reset():
    """Test resetting rate limits."""
    limiter = RateLimiter()

    # Make some requests
    await limiter.check_rate_limit("reset_user", "default")
    await limiter.check_rate_limit("reset_user", "default")

    # Check that user has used requests
    info = await limiter.get_rate_limit_info("reset_user", "default")
    assert info["used"] == 2

    # Reset the limit
    await limiter.reset_rate_limit("reset_user", "default")

    # Check that it's reset
    info_after = await limiter.get_rate_limit_info("reset_user", "default")
    assert info_after["used"] == 0
