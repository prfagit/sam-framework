"""Circuit breaker implementation for resilient API calls."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    Deque,
    Dict,
    Optional,
    ParamSpec,
    Tuple,
    TypeVar,
    TypedDict,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class CircuitState(Enum):
    """States of the circuit breaker."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject all calls
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker with environment variable support."""

    failure_threshold: int = 5  # Number of failures before opening
    recovery_timeout: float = 60.0  # Seconds before attempting recovery
    success_threshold: int = 3  # Successes needed to close from half-open
    timeout: float = 30.0  # Request timeout in seconds
    exceptions: Tuple[type[BaseException], ...] = (Exception,)  # Exceptions that count as failures

    # New configuration options
    half_open_max_calls: int = 1  # Max concurrent calls in half-open state
    metrics_window: int = 300  # Window for calculating metrics (seconds)
    min_requests: int = 10  # Minimum requests before considering failure rate
    failure_rate_threshold: float = 0.5  # 50% failure rate triggers open

    @classmethod
    def from_env(cls, name: str) -> "CircuitBreakerConfig":
        """Create configuration from environment variables.

        Supports endpoint-specific overrides:
        SAM_CB_{NAME}_FAILURE_THRESHOLD=5
        SAM_CB_{NAME}_RECOVERY_TIMEOUT=60
        SAM_CB_{NAME}_SUCCESS_THRESHOLD=3
        SAM_CB_{NAME}_TIMEOUT=30
        SAM_CB_{NAME}_HALF_OPEN_MAX_CALLS=1
        """
        prefix = f"SAM_CB_{name.upper().replace('-', '_')}_"

        return cls(
            failure_threshold=int(os.getenv(f"{prefix}FAILURE_THRESHOLD", "5")),
            recovery_timeout=float(os.getenv(f"{prefix}RECOVERY_TIMEOUT", "60.0")),
            success_threshold=int(os.getenv(f"{prefix}SUCCESS_THRESHOLD", "3")),
            timeout=float(os.getenv(f"{prefix}TIMEOUT", "30.0")),
            half_open_max_calls=int(os.getenv(f"{prefix}HALF_OPEN_MAX_CALLS", "1")),
            metrics_window=int(os.getenv(f"{prefix}METRICS_WINDOW", "300")),
            min_requests=int(os.getenv(f"{prefix}MIN_REQUESTS", "10")),
            failure_rate_threshold=float(os.getenv(f"{prefix}FAILURE_RATE_THRESHOLD", "0.5")),
        )


@dataclass
class CircuitBreakerStats:
    """Statistics tracking for circuit breaker with time-windowed metrics."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    total_timeouts: int = 0
    total_successes: int = 0

    # New: Time-windowed metrics
    state_transitions: int = 0  # Track state changes
    last_state_change: float = 0.0
    opened_count: int = 0  # Times circuit has opened
    half_open_calls: int = 0  # Current calls in half-open state

    # Request history for windowed metrics (timestamp, success)
    request_history: Deque[Tuple[float, bool]] = field(default_factory=deque)


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """Enhanced circuit breaker implementation with monitoring and configurability."""

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig.from_env(name)
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        self._event_callbacks: list[Callable[[str, CircuitState, CircuitState], None]] = []
        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout}s"
        )

    async def call(self, func: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute a function with circuit breaker protection."""
        async with self._lock:
            await self._check_state()

        if self.stats.state == CircuitState.OPEN:
            logger.warning(f"Circuit breaker '{self.name}' is OPEN, rejecting call")
            raise CircuitBreakerError(f"Circuit breaker '{self.name}' is open")

        # Enforce half-open max calls limit
        if self.stats.state == CircuitState.HALF_OPEN:
            if self.stats.half_open_calls >= self.config.half_open_max_calls:
                logger.debug(
                    f"Circuit breaker '{self.name}' HALF_OPEN max calls reached, rejecting"
                )
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is half-open (max concurrent calls reached)"
                )
            self.stats.half_open_calls += 1

        self.stats.total_requests += 1
        start_time = time.time()

        try:
            # Execute with timeout
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
            await self._on_success(start_time)
            return result

        except asyncio.TimeoutError:
            self.stats.total_timeouts += 1
            logger.warning(f"Circuit breaker '{self.name}' - request timeout")
            await self._on_failure(start_time)
            raise

        except self.config.exceptions as e:
            logger.warning(f"Circuit breaker '{self.name}' - failure: {e}")
            await self._on_failure(start_time)
            raise

        finally:
            # Decrement half-open call counter
            if self.stats.state == CircuitState.HALF_OPEN:
                async with self._lock:
                    self.stats.half_open_calls = max(0, self.stats.half_open_calls - 1)

    async def _check_state(self) -> None:
        """Check and update circuit breaker state."""
        current_time = time.time()

        if (
            self.stats.state == CircuitState.OPEN
            and current_time - self.stats.last_failure_time >= self.config.recovery_timeout
        ):
            logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN")
            self.stats.state = CircuitState.HALF_OPEN
            self.stats.success_count = 0

    async def _on_success(self, start_time: float) -> None:
        """Handle successful call with windowed metrics."""
        async with self._lock:
            self.stats.total_successes += 1
            self.stats.request_history.append((start_time, True))
            self._cleanup_old_requests()

            if self.stats.state == CircuitState.HALF_OPEN:
                self.stats.success_count += 1
                if self.stats.success_count >= self.config.success_threshold:
                    logger.info(f"Circuit breaker '{self.name}' transitioning to CLOSED")
                    await self._transition_state(CircuitState.CLOSED)
                    self.stats.failure_count = 0
                    self.stats.success_count = 0
            elif self.stats.state == CircuitState.CLOSED:
                self.stats.failure_count = 0

    async def _on_failure(self, start_time: float) -> None:
        """Handle failed call with windowed metrics."""
        async with self._lock:
            self.stats.failure_count += 1
            self.stats.total_failures += 1
            self.stats.last_failure_time = time.time()
            self.stats.request_history.append((start_time, False))
            self._cleanup_old_requests()

            if self.stats.state == CircuitState.HALF_OPEN:
                logger.info(
                    f"Circuit breaker '{self.name}' transitioning to OPEN (half-open failure)"
                )
                await self._transition_state(CircuitState.OPEN)
                self.stats.opened_count += 1
            elif self.stats.state == CircuitState.CLOSED:
                # Check failure threshold and failure rate
                should_open = False

                if self.stats.failure_count >= self.config.failure_threshold:
                    should_open = True
                    logger.warning(
                        f"Circuit breaker '{self.name}' failure threshold reached: "
                        f"{self.stats.failure_count}/{self.config.failure_threshold}"
                    )

                # Also check failure rate if we have enough requests
                recent_requests = len(self.stats.request_history)
                if recent_requests >= self.config.min_requests:
                    failures = sum(1 for _, success in self.stats.request_history if not success)
                    failure_rate = failures / recent_requests

                    if failure_rate >= self.config.failure_rate_threshold:
                        should_open = True
                        logger.warning(
                            f"Circuit breaker '{self.name}' failure rate threshold reached: "
                            f"{failure_rate:.1%} >= {self.config.failure_rate_threshold:.1%}"
                        )

                if should_open:
                    logger.warning(f"Circuit breaker '{self.name}' transitioning to OPEN")
                    await self._transition_state(CircuitState.OPEN)
                    self.stats.opened_count += 1

    def _cleanup_old_requests(self) -> None:
        """Remove requests outside the metrics window."""
        current_time = time.time()
        cutoff = current_time - self.config.metrics_window

        while self.stats.request_history and self.stats.request_history[0][0] < cutoff:
            self.stats.request_history.popleft()

    async def _transition_state(self, new_state: CircuitState) -> None:
        """Transition to a new state and notify callbacks."""
        old_state = self.stats.state
        if old_state != new_state:
            self.stats.state = new_state
            self.stats.state_transitions += 1
            self.stats.last_state_change = time.time()

            # Notify event callbacks
            for callback in self._event_callbacks:
                try:
                    callback(self.name, old_state, new_state)
                except Exception as e:
                    logger.error(f"Error in circuit breaker event callback: {e}")

    def on_state_change(self, callback: Callable[[str, CircuitState, CircuitState], None]) -> None:
        """Register a callback for state change events.

        Callback signature: (name: str, old_state: CircuitState, new_state: CircuitState)
        """
        self._event_callbacks.append(callback)

    async def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        async with self._lock:
            old_state = self.stats.state
            self.stats.state = CircuitState.CLOSED
            self.stats.failure_count = 0
            self.stats.success_count = 0
            self.stats.half_open_calls = 0
            logger.info(
                f"Circuit breaker '{self.name}' manually reset from {old_state.value} to CLOSED"
            )

    def get_stats(self) -> "CircuitBreakerStatsSnapshot":
        """Get current circuit breaker statistics with windowed metrics."""
        # Calculate windowed metrics
        recent_requests = len(self.stats.request_history)
        if recent_requests > 0:
            recent_failures = sum(1 for _, success in self.stats.request_history if not success)
            windowed_failure_rate = recent_failures / recent_requests
        else:
            windowed_failure_rate = 0.0

        return {
            "name": self.name,
            "state": self.stats.state.value,
            "failure_count": self.stats.failure_count,
            "total_requests": self.stats.total_requests,
            "total_failures": self.stats.total_failures,
            "total_successes": self.stats.total_successes,
            "total_timeouts": self.stats.total_timeouts,
            "failure_rate": (
                self.stats.total_failures / self.stats.total_requests
                if self.stats.total_requests > 0
                else 0.0
            ),
            "windowed_failure_rate": windowed_failure_rate,
            "windowed_requests": recent_requests,
            "last_failure_time": self.stats.last_failure_time,
            "state_transitions": self.stats.state_transitions,
            "last_state_change": self.stats.last_state_change,
            "opened_count": self.stats.opened_count,
            "half_open_calls": self.stats.half_open_calls,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "success_threshold": self.config.success_threshold,
                "timeout": self.config.timeout,
                "half_open_max_calls": self.config.half_open_max_calls,
                "metrics_window": self.config.metrics_window,
                "min_requests": self.config.min_requests,
                "failure_rate_threshold": self.config.failure_rate_threshold,
            },
        }


# Global registry of circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, config)
    return _circuit_breakers[name]


def circuit_breaker(
    name: str, config: Optional[CircuitBreakerConfig] = None
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator to add circuit breaker protection to async functions."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        breaker = get_circuit_breaker(name, config)

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


def get_all_circuit_breaker_stats() -> Dict[str, CircuitBreakerStatsSnapshot]:
    """Get statistics for all circuit breakers."""
    return {name: breaker.get_stats() for name, breaker in _circuit_breakers.items()}


class CircuitBreakerStatsSnapshot(TypedDict):
    name: str
    state: str
    failure_count: int
    total_requests: int
    total_failures: int
    total_successes: int
    total_timeouts: int
    failure_rate: float
    windowed_failure_rate: float
    windowed_requests: int
    last_failure_time: float
    state_transitions: int
    last_state_change: float
    opened_count: int
    half_open_calls: int
    config: Dict[str, Any]


async def reset_circuit_breaker(name: str) -> bool:
    """Reset a specific circuit breaker to CLOSED state.

    Returns:
        True if breaker exists and was reset, False otherwise
    """
    if name in _circuit_breakers:
        await _circuit_breakers[name].reset()
        return True
    return False


async def reset_all_circuit_breakers() -> int:
    """Reset all circuit breakers to CLOSED state.

    Returns:
        Number of circuit breakers reset
    """
    count = 0
    for breaker in _circuit_breakers.values():
        await breaker.reset()
        count += 1
    logger.info(f"Reset {count} circuit breakers")
    return count
