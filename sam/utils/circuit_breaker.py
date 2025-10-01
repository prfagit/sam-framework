"""Circuit breaker implementation for resilient API calls."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Awaitable, Callable, Dict, Optional, ParamSpec, Tuple, TypeVar, TypedDict

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
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Number of failures before opening
    recovery_timeout: float = 60.0  # Seconds before attempting recovery
    success_threshold: int = 3  # Successes needed to close from half-open
    timeout: float = 30.0  # Request timeout in seconds
    exceptions: Tuple[type[BaseException], ...] = (Exception,)  # Exceptions that count as failures


@dataclass
class CircuitBreakerStats:
    """Statistics tracking for circuit breaker."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    total_timeouts: int = 0


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """Circuit breaker implementation for resilient API calls."""

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        logger.info(f"Circuit breaker '{name}' initialized with config: {self.config}")

    async def call(self, func: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute a function with circuit breaker protection."""
        async with self._lock:
            await self._check_state()

        if self.stats.state == CircuitState.OPEN:
            logger.warning(f"Circuit breaker '{self.name}' is OPEN, rejecting call")
            raise CircuitBreakerError(f"Circuit breaker '{self.name}' is open")

        self.stats.total_requests += 1

        try:
            # Execute with timeout
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
            await self._on_success()
            return result

        except asyncio.TimeoutError:
            self.stats.total_timeouts += 1
            logger.warning(f"Circuit breaker '{self.name}' - request timeout")
            await self._on_failure()
            raise

        except self.config.exceptions as e:
            logger.warning(f"Circuit breaker '{self.name}' - failure: {e}")
            await self._on_failure()
            raise

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

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self.stats.state == CircuitState.HALF_OPEN:
                self.stats.success_count += 1
                if self.stats.success_count >= self.config.success_threshold:
                    logger.info(f"Circuit breaker '{self.name}' transitioning to CLOSED")
                    self.stats.state = CircuitState.CLOSED
                    self.stats.failure_count = 0
            elif self.stats.state == CircuitState.CLOSED:
                self.stats.failure_count = 0

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self.stats.failure_count += 1
            self.stats.total_failures += 1
            self.stats.last_failure_time = time.time()

            if self.stats.state == CircuitState.HALF_OPEN:
                logger.info(
                    f"Circuit breaker '{self.name}' transitioning to OPEN (half-open failure)"
                )
                self.stats.state = CircuitState.OPEN
            elif (
                self.stats.state == CircuitState.CLOSED
                and self.stats.failure_count >= self.config.failure_threshold
            ):
                logger.warning(f"Circuit breaker '{self.name}' transitioning to OPEN")
                self.stats.state = CircuitState.OPEN

    def get_stats(self) -> "CircuitBreakerStatsSnapshot":
        """Get current circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.stats.state.value,
            "failure_count": self.stats.failure_count,
            "total_requests": self.stats.total_requests,
            "total_failures": self.stats.total_failures,
            "total_timeouts": self.stats.total_timeouts,
            "failure_rate": (
                self.stats.total_failures / self.stats.total_requests
                if self.stats.total_requests > 0
                else 0
            ),
            "last_failure_time": self.stats.last_failure_time,
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
    total_timeouts: int
    failure_rate: float
    last_failure_time: float
