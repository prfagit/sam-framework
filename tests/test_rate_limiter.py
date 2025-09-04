import pytest
import asyncio
from sam.utils.rate_limiter import RateLimiter, RateLimit


@pytest.mark.asyncio
async def test_rate_limiter_without_redis():
    """Test rate limiter behavior when Redis is not available."""
    # Use invalid Redis URL to simulate Redis being unavailable
    limiter = RateLimiter("redis://invalid:6379/0")
    await limiter.connect()
    
    # Should allow requests when Redis is not connected
    allowed, info = await limiter.check_rate_limit("test_user", "default")
    assert allowed is True
    assert info["status"] == "no_limit"


@pytest.mark.asyncio
async def test_rate_limit_decorator():
    """Test rate limiting decorator functionality."""
    from sam.utils.decorators import rate_limit
    
    @rate_limit("default")
    async def test_function(args_dict):
        return {"success": True, "data": "test"}
    
    # Call with user identifier
    result = await test_function({"public_key": "test_user"})
    
    # Should succeed (no Redis connection, so rate limiting is disabled)
    assert result["success"] is True
    assert "rate_limit_info" in result or "error" not in result


@pytest.mark.asyncio
async def test_rate_limit_configuration():
    """Test that rate limit configurations are properly set."""
    limiter = RateLimiter()
    
    # Check that specific limits exist
    assert "pump_fun_buy" in limiter.limits
    assert "transfer_sol" in limiter.limits
    assert "launch_token" in limiter.limits
    
    # Check that launch_token has strict limits
    launch_limit = limiter.limits["launch_token"]
    assert launch_limit.requests == 2
    assert launch_limit.window == 300  # 5 minutes
    assert launch_limit.burst == 1
    
    # Check that transfer_sol has reasonable limits
    transfer_limit = limiter.limits["transfer_sol"]
    assert transfer_limit.requests == 5
    assert transfer_limit.window == 60
    assert transfer_limit.burst == 2


@pytest.mark.asyncio
async def test_retry_decorator():
    """Test retry decorator functionality."""
    from sam.utils.decorators import retry_with_backoff
    
    call_count = 0
    
    @retry_with_backoff(max_retries=2, base_delay=0.01)  # Fast delays for testing
    async def failing_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Simulated failure")
        return {"success": True}
    
    result = await failing_function()
    assert result["success"] is True
    assert call_count == 3  # Initial call + 2 retries


@pytest.mark.asyncio
async def test_log_execution_decorator():
    """Test log execution decorator."""
    from sam.utils.decorators import log_execution
    
    @log_execution(include_args=True, include_result=True)
    async def test_function(arg1, arg2="default"):
        return {"result": f"{arg1}-{arg2}"}
    
    result = await test_function("test", arg2="value")
    assert result["result"] == "test-value"