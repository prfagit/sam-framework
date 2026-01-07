import asyncio
import logging
import time
import os
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from collections import OrderedDict

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """Rate limit configuration with adaptive support."""

    requests: int  # Number of requests allowed
    window: int  # Time window in seconds
    burst: int  # Burst limit (immediate requests allowed)
    adaptive: bool = False  # Whether to adapt based on server responses
    last_adjusted: float = 0.0  # Timestamp of last adjustment


@dataclass
class RequestRecord:
    """Individual request record."""

    timestamp: float
    key: str


class RateLimiter:
    """Optimized in-memory rate limiter with LRU eviction and memory management."""

    def __init__(self, max_keys: int = 10000, cleanup_interval: int = 60):
        # In-memory storage for request history with LRU ordering
        self.request_history: OrderedDict[str, List[RequestRecord]] = OrderedDict()
        self.lock = asyncio.Lock()
        # Allow environment overrides for tuning without code changes
        try:
            self.max_keys = int(os.getenv("SAM_RL_MAX_KEYS", str(max_keys)))
        except Exception:
            self.max_keys = max_keys
        try:
            self.cleanup_interval = int(os.getenv("SAM_RL_CLEANUP_INTERVAL", str(cleanup_interval)))
        except Exception:
            self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task[None]] = None
        self._shutdown = False

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
            "pump_fun_buy": RateLimit(requests=10, window=60, burst=2),
            "pump_fun_sell": RateLimit(requests=10, window=60, burst=2),
            # Auth endpoint rate limits (stricter to prevent brute force)
            "auth_login": RateLimit(requests=10, window=60, burst=5),  # 10 attempts per minute
            "auth_register": RateLimit(requests=10, window=60, burst=5),  # 10 attempts per minute
            "auth_refresh": RateLimit(
                requests=20, window=60, burst=5
            ),  # 20 refresh attempts per minute
            # Default fallback
            "default": RateLimit(requests=60, window=60, burst=10),
        }

        logger.info(f"Initialized optimized rate limiter (max_keys: {self.max_keys})")

        # Start cleanup task
        # Only attempt to start if running in an event loop
        try:
            asyncio.get_running_loop()
            self._start_cleanup_task()
        except RuntimeError:
            # No running loop; caller may start later when appropriate
            pass

    def _start_cleanup_task(self) -> None:
        """Start the cleanup task."""
        # Only start if a running loop exists (tests may construct without loop)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_old_records())

    async def _evict_lru_keys(self, target_count: int) -> None:
        """Evict least recently used keys to make room."""
        evicted = 0
        while len(self.request_history) > target_count and evicted < 1000:  # Prevent infinite loop
            try:
                # Remove oldest (least recently used) key
                oldest_key, _ = self.request_history.popitem(last=False)
                evicted += 1
            except KeyError:
                break

        if evicted > 0:
            logger.debug(f"Evicted {evicted} LRU rate limit keys")

    def _touch_key(self, key: str) -> None:
        """Mark key as recently used by moving it to end of OrderedDict."""
        if key in self.request_history:
            # Move to end (most recently used)
            records = self.request_history.pop(key)
            self.request_history[key] = records

    async def _cleanup_old_records(self) -> None:
        """Optimized periodic cleanup with LRU eviction."""
        while not self._shutdown:
            try:
                await asyncio.sleep(self.cleanup_interval)

                if self._shutdown:
                    break

                current_time = time.time()

                async with self.lock:
                    initial_size = len(self.request_history)

                    # Clean up expired records first
                    keys_to_remove = []
                    cleaned_records = 0

                    for key, records in list(self.request_history.items()):
                        # Remove records older than 1 hour
                        cutoff_time = current_time - 3600
                        old_count = len(records)

                        self.request_history[key] = [
                            record for record in records if record.timestamp > cutoff_time
                        ]

                        cleaned_records += old_count - len(self.request_history[key])

                        # Remove empty keys
                        if not self.request_history[key]:
                            keys_to_remove.append(key)

                    for key in keys_to_remove:
                        del self.request_history[key]

                    # LRU eviction if still over limit
                    if len(self.request_history) > self.max_keys:
                        target_size = int(self.max_keys * 0.8)  # Reduce to 80% of max
                        await self._evict_lru_keys(target_size)

                    final_size = len(self.request_history)

                    if keys_to_remove or cleaned_records > 0:
                        logger.debug(
                            f"Rate limiter cleanup: removed {len(keys_to_remove)} keys, "
                            f"cleaned {cleaned_records} records, "
                            f"size: {initial_size} → {final_size}"
                        )

            except asyncio.CancelledError:
                logger.info("Rate limiter cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in rate limiter cleanup: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def check_rate_limit(
        self, key: str, limit_type: str = "default"
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Check if a request should be allowed based on rate limiting.

        Returns:
            tuple: (is_allowed: bool, info: Dict[str, Any])
        """
        async with self.lock:
            current_time = time.time()
            limit = self.limits.get(limit_type, self.limits["default"])

            # Check for LRU eviction before processing
            if len(self.request_history) >= self.max_keys and key not in self.request_history:
                await self._evict_lru_keys(self.max_keys - 1)

            # Get or create request history for this key
            if key not in self.request_history:
                self.request_history[key] = []
            else:
                # Touch key to mark as recently used
                self._touch_key(key)

            records = self.request_history[key]

            # Remove old records outside the time window
            window_start = current_time - limit.window
            recent_records = [r for r in records if r.timestamp > window_start]
            self.request_history[key] = recent_records

            # Count recent requests
            recent_count = len(recent_records)

            # Check if within limits
            if recent_count < limit.requests:
                # Allow the request
                new_record = RequestRecord(timestamp=current_time, key=key)
                self.request_history[key].append(new_record)

                return True, {
                    "allowed": True,
                    "limit": limit.requests,
                    "remaining": limit.requests - recent_count - 1,
                    "reset_time": window_start + limit.window,
                    "retry_after": 0,
                }
            else:
                # Rate limit exceeded
                # Calculate when the oldest request will expire
                oldest_record = min(recent_records, key=lambda r: r.timestamp)
                retry_after = oldest_record.timestamp + limit.window - current_time

                return False, {
                    "allowed": False,
                    "limit": limit.requests,
                    "remaining": 0,
                    "reset_time": oldest_record.timestamp + limit.window,
                    "retry_after": max(0, retry_after),
                }

    async def reset_rate_limit(self, key: str, limit_type: str = "default") -> None:
        """Reset rate limit for a specific key."""
        async with self.lock:
            if key in self.request_history:
                del self.request_history[key]
                logger.info(f"Reset rate limit for key: {key}")

    async def get_rate_limit_info(self, key: str, limit_type: str = "default") -> Dict[str, Any]:
        """Get current rate limit status for a key without making a request."""
        async with self.lock:
            current_time = time.time()
            limit = self.limits.get(limit_type, self.limits["default"])

            if key not in self.request_history:
                return {
                    "limit": limit.requests,
                    "remaining": limit.requests,
                    "used": 0,
                    "reset_time": current_time + limit.window,
                }

            # Count recent requests within the window
            window_start = current_time - limit.window
            recent_records = [r for r in self.request_history[key] if r.timestamp > window_start]
            used_count = len(recent_records)

            reset_time = current_time + limit.window
            if recent_records:
                oldest_record = min(recent_records, key=lambda r: r.timestamp)
                reset_time = oldest_record.timestamp + limit.window

            return {
                "limit": limit.requests,
                "remaining": max(0, limit.requests - used_count),
                "used": used_count,
                "reset_time": reset_time,
            }

    async def shutdown(self) -> None:
        """Shutdown the rate limiter and cleanup resources."""
        self._shutdown = True
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self.lock:
            self.request_history.clear()

        logger.info("Rate limiter shutdown completed")

    async def update_from_headers(
        self, limit_type: str, headers: Dict[str, str], response_status: int = 200
    ) -> None:
        """
        Update rate limits adaptively based on HTTP response headers.

        Args:
            limit_type: Type of rate limit to update
            headers: HTTP response headers (case-insensitive)
            response_status: HTTP status code
        """
        # Normalize headers to lowercase
        normalized_headers = {k.lower(): v for k, v in headers.items()}

        # Check if this limit type supports adaptive updates
        if limit_type not in self.limits:
            return

        limit = self.limits[limit_type]
        if not limit.adaptive:
            return

        current_time = time.time()

        # Respect Retry-After header (429 Too Many Requests)
        if response_status == 429 and "retry-after" in normalized_headers:
            try:
                retry_after = int(normalized_headers["retry-after"])
                # Temporarily reduce rate for this key type
                if retry_after > 0:
                    logger.warning(
                        f"Rate limit hit for {limit_type}, reducing requests for {retry_after}s"
                    )
                    # Reduce rate by 50% and increase window
                    limit.requests = max(1, limit.requests // 2)
                    limit.window = retry_after
                    limit.last_adjusted = current_time
            except (ValueError, TypeError):
                pass

        # Check for X-RateLimit headers (standard rate limit headers)
        elif all(h in normalized_headers for h in ["x-ratelimit-limit", "x-ratelimit-remaining"]):
            try:
                rate_limit_max = int(normalized_headers["x-ratelimit-limit"])
                rate_limit_remaining = int(normalized_headers["x-ratelimit-remaining"])

                # If we're getting close to limit, be more conservative
                usage_pct = (rate_limit_max - rate_limit_remaining) / rate_limit_max
                if usage_pct > 0.8:  # 80% used
                    logger.debug(
                        f"Rate limit at {usage_pct * 100:.0f}% for {limit_type}, reducing requests"
                    )
                    # Reduce by 20%
                    limit.requests = max(1, int(rate_limit_max * 0.8))
                    limit.last_adjusted = current_time
                elif (
                    usage_pct < 0.3 and (current_time - limit.last_adjusted) > 300
                ):  # 30% used, 5min since last adjust
                    # Gradually increase if we're well under limit
                    logger.debug(
                        f"Rate limit at {usage_pct * 100:.0f}% for {limit_type}, increasing requests"
                    )
                    limit.requests = min(rate_limit_max, int(limit.requests * 1.2))
                    limit.last_adjusted = current_time
            except (ValueError, TypeError, KeyError):
                pass

    async def enable_adaptive_limiting(self, limit_type: str) -> None:
        """Enable adaptive rate limiting for a specific limit type."""
        if limit_type in self.limits:
            self.limits[limit_type].adaptive = True
            logger.info(f"Enabled adaptive rate limiting for: {limit_type}")

    async def disable_adaptive_limiting(self, limit_type: str) -> None:
        """Disable adaptive rate limiting for a specific limit type."""
        if limit_type in self.limits:
            self.limits[limit_type].adaptive = False
            logger.info(f"Disabled adaptive rate limiting for: {limit_type}")

    async def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics with adaptive limit info."""
        async with self.lock:
            total_records = sum(len(records) for records in self.request_history.values())

            adaptive_limits = {
                name: {
                    "requests": limit.requests,
                    "window": limit.window,
                    "adaptive": limit.adaptive,
                    "last_adjusted": limit.last_adjusted,
                }
                for name, limit in self.limits.items()
                if limit.adaptive
            }

            return {
                "total_keys": len(self.request_history),
                "max_keys": self.max_keys,
                "total_records": total_records,
                "cleanup_interval": self.cleanup_interval,
                "is_shutdown": self._shutdown,
                "memory_usage_pct": (len(self.request_history) / self.max_keys) * 100,
                "adaptive_limits": adaptive_limits,
            }


# Global rate limiter instance
_global_rate_limiter: Optional[RateLimiter] = None
_limiter_lock: Optional[asyncio.Lock] = None


def _get_limiter_lock() -> asyncio.Lock:
    """Get or create the rate limiter initialization lock."""
    global _limiter_lock
    if _limiter_lock is None:
        _limiter_lock = asyncio.Lock()
    return _limiter_lock


async def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter instance (thread-safe with double-check locking)."""
    global _global_rate_limiter

    # Fast path - limiter already exists
    if _global_rate_limiter is not None:
        return _global_rate_limiter

    # Acquire lock for initialization
    lock = _get_limiter_lock()
    async with lock:
        # Double-check inside lock to prevent race condition
        if _global_rate_limiter is None:
            _global_rate_limiter = RateLimiter()
        return _global_rate_limiter


async def cleanup_rate_limiter() -> None:
    """Cleanup global rate limiter (thread-safe)."""
    global _global_rate_limiter, _limiter_lock

    if _global_rate_limiter is None:
        return

    lock = _get_limiter_lock()
    async with lock:
        if _global_rate_limiter:
            await _global_rate_limiter.shutdown()
            _global_rate_limiter = None
        # Reset lock for potential re-initialization
        _limiter_lock = None


async def check_rate_limit(
    identifier: str, limit_type: str = "default"
) -> tuple[bool, Dict[str, Any]]:
    """Global function to check rate limits."""
    limiter = await get_rate_limiter()
    return await limiter.check_rate_limit(identifier, limit_type)


async def rate_limited(identifier: str, limit_type: str = "default") -> bool:
    """Check if an identifier is currently rate limited."""
    allowed, info = await check_rate_limit(identifier, limit_type)
    return not allowed
