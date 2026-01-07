import asyncio
import logging
import time
import traceback
import json
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar, Union, cast
from dataclasses import dataclass
from enum import Enum
import os

logger = logging.getLogger(__name__)

HealthCheckFunc = Callable[[], Union[Awaitable[Any], Any]]
F = TypeVar("F", bound=Callable[..., Any])


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ErrorRecord:
    """Error record for tracking and monitoring."""

    timestamp: datetime
    error_type: str
    error_message: str
    severity: ErrorSeverity
    component: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None


class ErrorTracker:
    """Track and monitor errors across the SAM framework."""

    def __init__(self, db_path: str = ".sam/errors.db", persistent: bool = True):
        self.db_path = db_path
        self.persistent = persistent
        self.error_counts: Dict[str, int] = {}
        self.last_cleanup = datetime.utcnow()
        self._memory_records: List[ErrorRecord] = []

        # Ensure directory exists (handle case where db_path has no directory)
        if self.persistent:
            dirpath = os.path.dirname(db_path) or "."
            os.makedirs(dirpath, exist_ok=True)
            logger.info(f"Initialized error tracker: {db_path}")
        else:
            logger.info("Initialized error tracker (persistence disabled)")

    async def initialize(self) -> None:
        """Initialize error tracking database using connection pool."""
        if not self.persistent:
            return

        from ..utils.connection_pool import get_db_connection

        async with get_db_connection(self.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    component TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    context TEXT,
                    stack_trace TEXT
                )
            """)

            # Create indexes for performance
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON errors(timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_component ON errors(component)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON errors(severity)")
            # Add missing index for user_id (found in code review)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_time ON errors(user_id, timestamp DESC)"
            )

            await conn.commit()

        logger.info("Error tracking database initialized")

    async def log_error(
        self,
        error: Exception,
        component: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an error to the tracking system."""
        try:
            error_record = ErrorRecord(
                timestamp=datetime.utcnow(),
                error_type=type(error).__name__,
                error_message=str(error),
                severity=severity,
                component=component,
                session_id=session_id,
                user_id=user_id,
                context=context,
                stack_trace=traceback.format_exc(),
            )

            await self._store_error(error_record)

            # Update in-memory counters
            key = f"{component}_{error_record.error_type}"
            self.error_counts[key] = self.error_counts.get(key, 0) + 1

            # Log to standard logger based on severity
            if severity == ErrorSeverity.CRITICAL:
                logger.critical(f"CRITICAL ERROR in {component}: {error}")
            elif severity == ErrorSeverity.HIGH:
                logger.error(f"HIGH severity error in {component}: {error}")
            elif severity == ErrorSeverity.MEDIUM:
                logger.warning(f"MEDIUM severity error in {component}: {error}")
            else:
                logger.debug(f"LOW severity error in {component}: {error}")

        except Exception as e:
            # Don't let error logging break the main flow
            logger.error(f"Failed to log error: {e}")

    async def _store_error(self, error_record: ErrorRecord) -> None:
        """Store error record."""
        if not self.persistent:
            self._memory_records.append(error_record)
            return

        try:
            from ..utils.connection_pool import get_db_connection

            async with get_db_connection(self.db_path) as conn:
                await conn.execute(
                    """
                    INSERT INTO errors (
                        timestamp, error_type, error_message, severity,
                        component, session_id, user_id, context, stack_trace
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        error_record.timestamp.isoformat(),
                        error_record.error_type,
                        error_record.error_message,
                        error_record.severity.value,
                        error_record.component,
                        error_record.session_id,
                        error_record.user_id,
                        json.dumps(error_record.context) if error_record.context else None,
                        error_record.stack_trace,
                    ),
                )
                await conn.commit()

        except Exception as e:
            logger.error(f"Failed to store error record: {e}")

    async def get_error_stats(self, hours_back: int = 24) -> Dict[str, Any]:
        """Get error statistics for the last N hours."""
        if not self.persistent:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
            severity_counts: Dict[str, int] = {}
            component_counts: Dict[str, int] = {}
            critical_errors = []

            for record in self._memory_records:
                if record.timestamp < cutoff_time:
                    continue

                severity_counts[record.severity.value] = (
                    severity_counts.get(record.severity.value, 0) + 1
                )
                component_counts[record.component] = component_counts.get(record.component, 0) + 1

                if record.severity == ErrorSeverity.CRITICAL and len(critical_errors) < 5:
                    critical_errors.append(
                        {
                            "timestamp": record.timestamp.isoformat(),
                            "component": record.component,
                            "error_type": record.error_type,
                            "error_message": record.error_message,
                        }
                    )

            return {
                "time_window_hours": hours_back,
                "severity_counts": severity_counts,
                "component_counts": component_counts,
                "critical_errors": critical_errors,
                "total_errors": sum(severity_counts.values()),
                "in_memory_counts": dict(self.error_counts),
            }

        from ..utils.connection_pool import get_db_connection

        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        cutoff_str = cutoff_time.isoformat()

        try:
            async with get_db_connection(self.db_path) as conn:
                # Total errors by severity
                cursor = await conn.execute(
                    """
                    SELECT severity, COUNT(*) 
                    FROM errors 
                    WHERE timestamp > ? 
                    GROUP BY severity
                """,
                    (cutoff_str,),
                )

                db_severity_counts: Dict[str, int] = {
                    row[0]: row[1] for row in await cursor.fetchall()
                }

                # Errors by component
                cursor = await conn.execute(
                    """
                    SELECT component, COUNT(*) 
                    FROM errors 
                    WHERE timestamp > ? 
                    GROUP BY component 
                    ORDER BY COUNT(*) DESC 
                    LIMIT 10
                """,
                    (cutoff_str,),
                )

                db_component_counts: Dict[str, int] = {
                    row[0]: row[1] for row in await cursor.fetchall()
                }

                # Recent critical errors
                cursor = await conn.execute(
                    """
                    SELECT timestamp, component, error_type, error_message
                    FROM errors
                    WHERE timestamp > ? AND severity = 'critical'
                    ORDER BY timestamp DESC
                    LIMIT 5
                """,
                    (cutoff_str,),
                )

                db_critical_errors: list[dict[str, Any]] = []
                for row in await cursor.fetchall():
                    db_critical_errors.append(
                        {
                            "timestamp": row[0],
                            "component": row[1],
                            "error_type": row[2],
                            "error_message": row[3],
                        }
                    )

                return {
                    "time_window_hours": hours_back,
                    "severity_counts": db_severity_counts,
                    "component_counts": db_component_counts,
                    "critical_errors": db_critical_errors,
                    "total_errors": sum(db_severity_counts.values()),
                    "in_memory_counts": dict(self.error_counts),
                }

        except Exception as e:
            logger.error(f"Failed to get error stats: {e}")
            return {"error": str(e)}

    async def cleanup_old_errors(self, days_old: int = 30) -> int:
        """Clean up old error records."""
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        if not self.persistent:
            before = len(self._memory_records)
            self._memory_records = [
                record for record in self._memory_records if record.timestamp >= cutoff_date
            ]
            deleted = before - len(self._memory_records)
            if deleted:
                logger.info(f"Cleaned up {deleted} in-memory error records")
            return deleted

        from ..utils.connection_pool import get_db_connection

        cutoff_str = cutoff_date.isoformat()

        try:
            async with get_db_connection(self.db_path) as conn:
                cursor = await conn.execute("DELETE FROM errors WHERE timestamp < ?", (cutoff_str,))

                deleted_count = cursor.rowcount or 0
                await conn.commit()

            logger.info(f"Cleaned up {deleted_count} old error records")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old errors: {e}")
            return 0


class CircuitBreaker:
    """Circuit breaker pattern for handling cascading failures."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half_open

        logger.info(f"Initialized circuit breaker: {name}")

    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset the circuit breaker."""
        return (
            self.state == "open"
            and self.last_failure_time is not None
            and time.time() - self.last_failure_time >= self.recovery_timeout
        )

    async def call(
        self,
        func: Callable[..., Union[Awaitable[Any], Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
                logger.info(f"Circuit breaker {self.name} attempting recovery")
            else:
                raise Exception(f"Circuit breaker {self.name} is open")

        try:
            if asyncio.iscoroutinefunction(func):
                result = await cast(Callable[..., Awaitable[Any]], func)(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Success - reset failure count
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
                logger.info(f"Circuit breaker {self.name} recovered successfully")

            return result

        except self.expected_exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(
                    f"Circuit breaker {self.name} opened after {self.failure_count} failures"
                )

            raise e


class HealthChecker:
    """Health monitoring for SAM framework components."""

    def __init__(self) -> None:
        self.checks: Dict[str, Dict[str, Any]] = {}
        self.last_check_time: Dict[str, float] = {}

    def register_health_check(
        self,
        name: str,
        check_func: HealthCheckFunc,
        interval: int = 60,
    ) -> None:
        """Register a health check function."""
        self.checks[name] = {
            "func": check_func,
            "interval": interval,
            "last_result": None,
            "last_check": 0,
        }
        logger.info(f"Registered health check: {name}")

    async def run_health_checks(self) -> Dict[str, Optional[Dict[str, Any]]]:
        """Run all health checks and return results."""
        results: Dict[str, Optional[Dict[str, Any]]] = {}
        current_time = time.time()

        for name, check in self.checks.items():
            # Only run check if interval has elapsed
            if current_time - check["last_check"] >= check["interval"]:
                try:
                    func = check["func"]
                    if asyncio.iscoroutinefunction(func):
                        result = await cast(Callable[..., Awaitable[Any]], func)()
                    else:
                        result = func()

                    check["last_result"] = {
                        "status": "healthy",
                        "timestamp": datetime.utcnow().isoformat(),
                        "details": result,
                    }
                    check["last_check"] = current_time

                except Exception as e:
                    check["last_result"] = {
                        "status": "unhealthy",
                        "timestamp": datetime.utcnow().isoformat(),
                        "error": str(e),
                    }
                    check["last_check"] = current_time

            results[name] = check["last_result"]

        return results


# Global instances
_error_tracker: Optional[ErrorTracker] = None
_health_checker: Optional[HealthChecker] = None


async def get_error_tracker() -> ErrorTracker:
    """Get the global error tracker instance."""
    global _error_tracker
    if _error_tracker is None:
        db_path = os.getenv("SAM_ERROR_DB_PATH", ".sam/errors.db")
        test_mode = os.getenv("SAM_TEST_MODE") == "1"
        force_persist = os.getenv("SAM_ERROR_TRACKER_PERSIST", "0") == "1"
        persistent = force_persist or not test_mode
        _error_tracker = ErrorTracker(db_path=db_path, persistent=persistent)
        await _error_tracker.initialize()
    return _error_tracker


def get_health_checker() -> HealthChecker:
    """Get the global health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


async def log_error(
    error: Exception,
    component: str,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    **kwargs: Any,
) -> None:
    """Convenience function to log errors."""
    tracker = await get_error_tracker()
    await tracker.log_error(error, component, severity, **kwargs)


def handle_errors(
    component: str,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
) -> Callable[[F], F]:
    """Decorator for automatic error handling and logging."""

    def decorator(func: F) -> F:
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                await log_error(e, component, severity)
                raise

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # For sync functions, we can't await log_error
                logger.error(f"Error in {component}: {e}")
                raise

        if asyncio.iscoroutinefunction(func):
            return cast(F, async_wrapper)
        return cast(F, sync_wrapper)

    return decorator
