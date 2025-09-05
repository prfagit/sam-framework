import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from collections import OrderedDict

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """Rate limit configuration."""
    requests: int  # Number of requests allowed
    window: int    # Time window in seconds
    burst: int     # Burst limit (immediate requests allowed)


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
        self.max_keys = max_keys
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
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
            
            # Default fallback
            "default": RateLimit(requests=60, window=60, burst=10)
        }
        
        logger.info(f"Initialized optimized rate limiter (max_keys: {max_keys})")
        
        # Start cleanup task
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start the cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_old_records())
    
    async def _evict_lru_keys(self, target_count: int):
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
    
    def _touch_key(self, key: str):
        """Mark key as recently used by moving it to end of OrderedDict."""
        if key in self.request_history:
            # Move to end (most recently used)
            records = self.request_history.pop(key)
            self.request_history[key] = records
    
    async def _cleanup_old_records(self):
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
                            record for record in records 
                            if record.timestamp > cutoff_time
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
    
    async def check_rate_limit(self, key: str, limit_type: str = "default") -> tuple[bool, Dict[str, Any]]:
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
                    "retry_after": 0
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
                    "retry_after": max(0, retry_after)
                }
    
    async def reset_rate_limit(self, key: str, limit_type: str = "default"):
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
                    "reset_time": current_time + limit.window
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
                "reset_time": reset_time
            }
    
    async def shutdown(self):
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
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        async with self.lock:
            total_records = sum(len(records) for records in self.request_history.values())
            
            return {
                "total_keys": len(self.request_history),
                "max_keys": self.max_keys,
                "total_records": total_records,
                "cleanup_interval": self.cleanup_interval,
                "is_shutdown": self._shutdown,
                "memory_usage_pct": (len(self.request_history) / self.max_keys) * 100
            }


# Global rate limiter instance
_global_rate_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _global_rate_limiter
    
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter()
    
    return _global_rate_limiter


async def cleanup_rate_limiter():
    """Cleanup global rate limiter."""
    global _global_rate_limiter
    if _global_rate_limiter:
        await _global_rate_limiter.shutdown()
        _global_rate_limiter = None


async def check_rate_limit(identifier: str, limit_type: str = "default") -> tuple[bool, Dict[str, Any]]:
    """Global function to check rate limits."""
    limiter = await get_rate_limiter()
    return await limiter.check_rate_limit(identifier, limit_type)


async def rate_limited(identifier: str, limit_type: str = "default"):
    """Check if an identifier is currently rate limited."""
    allowed, info = await check_rate_limit(identifier, limit_type)
    return not allowed