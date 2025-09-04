import redis.asyncio as aioredis
import asyncio
import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """Rate limit configuration."""
    requests: int  # Number of requests allowed
    window: int    # Time window in seconds
    burst: int     # Burst limit (immediate requests allowed)


class RateLimiter:
    """Redis-based rate limiter using token bucket algorithm."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.connected = False
        
        # Default rate limits per endpoint/tool
        self.limits = {
            # Solana RPC limits
            "solana_rpc": RateLimit(requests=100, window=60, burst=10),
            
            # External API limits
            "pump_fun": RateLimit(requests=30, window=60, burst=5),
            "jupiter": RateLimit(requests=60, window=60, burst=10),
            "dexscreener": RateLimit(requests=300, window=60, burst=20),
            
            # Tool-specific limits
            "transfer_sol": RateLimit(requests=5, window=60, burst=2),
            "pump_fun_buy": RateLimit(requests=10, window=60, burst=3),
            "pump_fun_sell": RateLimit(requests=10, window=60, burst=3),
            "launch_token": RateLimit(requests=2, window=300, burst=1),  # Very restrictive
            
            # Default fallback
            "default": RateLimit(requests=60, window=60, burst=10)
        }
        
        logger.info(f"Initialized rate limiter with Redis URL: {redis_url}")
    
    async def connect(self):
        """Connect to Redis."""
        try:
            self.redis = aioredis.from_url(self.redis_url, decode_responses=True)
            # Test connection
            await self.redis.ping()
            self.connected = True
            logger.info("Successfully connected to Redis for rate limiting")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Rate limiting disabled.")
            self.connected = False
    
    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.aclose()
            self.connected = False
    
    async def check_rate_limit(self, key: str, limit_type: str = "default") -> tuple[bool, Dict[str, Any]]:
        """
        Check if request is within rate limit using token bucket algorithm.
        
        Returns:
            (allowed: bool, info: dict) - Whether request is allowed and rate limit info
        """
        if not self.connected:
            # If Redis is not available, allow all requests but log warning
            logger.debug(f"Rate limiter not connected, allowing request: {key}")
            return True, {"status": "no_limit", "reason": "redis_unavailable"}
        
        limit = self.limits.get(limit_type, self.limits["default"])
        now = time.time()
        
        # Redis key for this rate limit bucket
        bucket_key = f"rate_limit:{limit_type}:{key}"
        
        try:
            # Get current bucket state
            pipe = self.redis.pipeline()
            pipe.hgetall(bucket_key)
            result = await pipe.execute()
            bucket = result[0] if result else {}
            
            # Initialize bucket if it doesn't exist
            if not bucket:
                bucket = {
                    "tokens": str(limit.burst),
                    "last_refill": str(now),
                    "total_requests": "0"
                }
            
            tokens = float(bucket.get("tokens", limit.burst))
            last_refill = float(bucket.get("last_refill", now))
            total_requests = int(bucket.get("total_requests", 0))
            
            # Calculate tokens to add based on time elapsed
            time_passed = now - last_refill
            tokens_to_add = time_passed * (limit.requests / limit.window)
            tokens = min(limit.burst, tokens + tokens_to_add)
            
            # Check if request can be allowed
            if tokens >= 1.0:
                # Allow request and consume token
                tokens -= 1.0
                total_requests += 1
                
                # Update bucket in Redis
                pipe = self.redis.pipeline()
                pipe.hset(bucket_key, mapping={
                    "tokens": str(tokens),
                    "last_refill": str(now),
                    "total_requests": str(total_requests)
                })
                pipe.expire(bucket_key, limit.window * 2)  # Expire after 2x window
                await pipe.execute()
                
                logger.debug(f"Rate limit ALLOWED for {key} ({limit_type}): {tokens:.2f} tokens remaining")
                return True, {
                    "status": "allowed",
                    "tokens_remaining": tokens,
                    "limit": limit.requests,
                    "window": limit.window,
                    "total_requests": total_requests
                }
            else:
                # Rate limit exceeded
                retry_after = max(1, int((1.0 - tokens) * (limit.window / limit.requests)))
                
                logger.warning(f"Rate limit EXCEEDED for {key} ({limit_type}): retry after {retry_after}s")
                return False, {
                    "status": "rate_limited",
                    "retry_after": retry_after,
                    "tokens_remaining": tokens,
                    "limit": limit.requests,
                    "window": limit.window,
                    "total_requests": total_requests
                }
                
        except Exception as e:
            logger.error(f"Rate limiter error for {key}: {e}")
            # On error, allow request but log the issue
            return True, {"status": "error", "error": str(e)}
    
    async def reset_rate_limit(self, key: str, limit_type: str = "default"):
        """Reset rate limit for a specific key (admin function)."""
        if not self.connected:
            return
        
        bucket_key = f"rate_limit:{limit_type}:{key}"
        try:
            await self.redis.delete(bucket_key)
            logger.info(f"Reset rate limit for {key} ({limit_type})")
        except Exception as e:
            logger.error(f"Failed to reset rate limit for {key}: {e}")
    
    async def get_rate_limit_info(self, key: str, limit_type: str = "default") -> Dict[str, Any]:
        """Get current rate limit status for a key."""
        if not self.connected:
            return {"status": "unavailable"}
        
        bucket_key = f"rate_limit:{limit_type}:{key}"
        limit = self.limits.get(limit_type, self.limits["default"])
        
        try:
            bucket = await self.redis.hgetall(bucket_key)
            if not bucket:
                return {
                    "status": "clean",
                    "tokens_available": limit.burst,
                    "limit": limit.requests,
                    "window": limit.window
                }
            
            tokens = float(bucket.get("tokens", limit.burst))
            total_requests = int(bucket.get("total_requests", 0))
            
            return {
                "status": "active",
                "tokens_available": tokens,
                "total_requests": total_requests,
                "limit": limit.requests,
                "window": limit.window
            }
            
        except Exception as e:
            logger.error(f"Failed to get rate limit info for {key}: {e}")
            return {"status": "error", "error": str(e)}


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        from ..config.settings import Settings
        _rate_limiter = RateLimiter(Settings.REDIS_URL)
        await _rate_limiter.connect()
    return _rate_limiter


async def check_rate_limit(identifier: str, limit_type: str = "default") -> tuple[bool, Dict[str, Any]]:
    """Convenience function to check rate limits."""
    limiter = await get_rate_limiter()
    return await limiter.check_rate_limit(identifier, limit_type)


async def rate_limited(identifier: str, limit_type: str = "default"):
    """
    Decorator/context manager for rate limiting.
    Raises RateLimitExceeded if limit is exceeded.
    """
    allowed, info = await check_rate_limit(identifier, limit_type)
    if not allowed:
        raise RateLimitExceeded(
            f"Rate limit exceeded for {limit_type}. Retry after {info.get('retry_after', 60)} seconds",
            retry_after=info.get('retry_after', 60),
            info=info
        )
    return info


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, message: str, retry_after: int = 60, info: Dict[str, Any] = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.info = info or {}