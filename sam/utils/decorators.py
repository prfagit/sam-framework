import asyncio
import functools
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Tuple

from .error_handling import ErrorSeverity, get_error_tracker
from .rate_limiter import check_rate_limit
from ..config.settings import Settings

logger = logging.getLogger(__name__)


CallableDictAsync = Callable[..., Awaitable[Dict[str, Any]]]
CallableAsync = Callable[..., Awaitable[Any]]


def rate_limit(
    limit_type: str = "default",
    identifier_key: Optional[str] = None,
) -> Callable[[CallableDictAsync], CallableDictAsync]:
    """
    Decorator to add rate limiting to tool functions.

    Args:
        limit_type: Type of rate limit to apply (matches rate_limiter.py limits)
        identifier_key: Key from function args to use as identifier (defaults to "public_key" or "user_id")
    """

    def decorator(func: CallableDictAsync) -> CallableDictAsync:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            # Extract identifier from function arguments
            kwargs_dict: Dict[str, Any] = dict(kwargs)
            identifier: Optional[str] = None

            # Check kwargs for identifier
            if identifier_key and identifier_key in kwargs_dict:
                identifier = kwargs_dict[identifier_key]
            elif "public_key" in kwargs_dict:
                identifier = kwargs_dict["public_key"]
            elif "user_id" in kwargs_dict:
                identifier = kwargs_dict["user_id"]

            # If args is a dict (common for tool handlers), check there too
            if not identifier and args and isinstance(args[0], dict):
                arg_dict = args[0]
                if identifier_key and identifier_key in arg_dict:
                    identifier = arg_dict[identifier_key]
                elif "public_key" in arg_dict:
                    identifier = arg_dict["public_key"]
                elif "user_id" in arg_dict:
                    identifier = arg_dict["user_id"]

            # Default identifier if none found
            if not identifier:
                identifier = "anonymous"

            # Check if rate limiting is enabled
            if not Settings.RATE_LIMITING_ENABLED:
                # Rate limiting disabled, execute function directly
                return await func(*args, **kwargs)

            # Check rate limit
            try:
                allowed, info = await check_rate_limit(identifier, limit_type)

                if not allowed:
                    logger.warning(
                        f"Rate limit exceeded for {func.__name__}: {identifier} ({limit_type})"
                    )
                    return {
                        "error": f"Rate limit exceeded. Please wait {info.get('retry_after', 60)} seconds before trying again.",
                        "rate_limit_info": info,
                    }

                # Execute the original function
                result = await func(*args, **kwargs)

                # Add rate limit info to successful responses
                if isinstance(result, dict) and "error" not in result:
                    result["rate_limit_info"] = {
                        "remaining": info.get("remaining", 0),
                        "limit": info.get("limit", 0),
                        "reset_time": info.get("reset_time", 0),
                    }

                return result

            except Exception as e:
                logger.error(f"Rate limiter error in {func.__name__}: {e}")
                # On rate limiter error, execute function anyway but log the issue
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Callable[[CallableDictAsync], CallableDictAsync]:
    """
    Decorator to add retry logic with exponential backoff for API calls.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        backoff_factor: Multiplier for delay on each retry
    """

    def decorator(func: CallableDictAsync) -> CallableDictAsync:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    if attempt < max_retries:
                        delay = base_delay * (backoff_factor**attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}: {e}"
                        )

            # If we get here, all retries failed
            error_message = f"Operation failed after {max_retries + 1} attempts: {last_exception}"
            return {
                "error": error_message,
                "retry_attempts": max_retries + 1,
            }

        return wrapper

    return decorator


def log_execution(
    include_args: bool = False,
    include_result: bool = False,
) -> Callable[[CallableAsync], CallableAsync]:
    """
    Decorator to log function execution for debugging and monitoring.

    Args:
        include_args: Whether to log function arguments
        include_result: Whether to log function result
    """

    def decorator(func: CallableAsync) -> CallableAsync:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            func_name = f"{func.__module__}.{func.__name__}"

            # Log function entry
            if include_args:
                logger.debug(f"Executing {func_name} with args={args}, kwargs={kwargs}")
            else:
                logger.debug(f"Executing {func_name}")

            try:
                result = await func(*args, **kwargs)

                execution_time = time.time() - start_time

                # Log successful execution
                if include_result:
                    logger.debug(f"Completed {func_name} in {execution_time:.3f}s: {result}")
                else:
                    logger.debug(f"Completed {func_name} in {execution_time:.3f}s")

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"Failed {func_name} after {execution_time:.3f}s: {e}")
                raise

        return wrapper

    return decorator


def validate_args(**validators: Callable[[Any], Any]) -> Callable[[CallableAsync], CallableAsync]:
    """
    Decorator to validate function arguments using custom validators.

    Args:
        **validators: Mapping of argument name to validator function
    """

    def decorator(func: CallableAsync) -> CallableAsync:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            kwargs_dict: Dict[str, Any] = dict(kwargs)
            # Validate kwargs
            for arg_name, validator in validators.items():
                if arg_name in kwargs_dict:
                    try:
                        validator(kwargs_dict[arg_name])
                    except Exception as e:
                        return {"error": f"Validation failed for {arg_name}: {e}"}

            # If first arg is a dict (common for tool handlers), validate that too
            if args and isinstance(args[0], dict):
                arg_dict = args[0]
                for arg_name, validator in validators.items():
                    if arg_name in arg_dict:
                        try:
                            validator(arg_dict[arg_name])
                        except Exception as e:
                            return {"error": f"Validation failed for {arg_name}: {e}"}

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def safe_async_operation(
    component: str,
    error_severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    fallback_value: Any = None,
    log_args: bool = False,
    log_result: bool = False,
    max_retries: int = 0,
    retry_delay: float = 1.0,
) -> Callable[[CallableAsync], CallableAsync]:
    """Enhanced decorator for safe async operations with comprehensive error handling."""

    def decorator(func: CallableAsync) -> CallableAsync:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            attempt = 0
            last_error = None

            kwargs_dict: Dict[str, Any] = dict(kwargs)

            if log_args:
                safe_args = _sanitize_args(args, kwargs_dict)
                logger.debug(f"{component}.{func.__name__} called with args: {safe_args}")
            else:
                logger.debug(f"{component}.{func.__name__} called")

            while attempt <= max_retries:
                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)

                    execution_time = time.time() - start_time
                    logger.debug(f"{component}.{func.__name__} completed in {execution_time:.3f}s")

                    if log_result and result is not None:
                        safe_result = _sanitize_result(result)
                        logger.debug(f"{component}.{func.__name__} result: {safe_result}")

                    return result

                except Exception as exc:  # noqa: BLE001
                    attempt += 1
                    last_error = exc
                    execution_time = time.time() - start_time

                    error_context = {
                        "function": func.__name__,
                        "component": component,
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "execution_time": execution_time,
                        "error_type": type(exc).__name__,
                    }

                    try:
                        error_tracker = await get_error_tracker()
                        await error_tracker.log_error(
                            error=exc,
                            component=component,
                            severity=error_severity,
                            context=error_context,
                        )
                    except Exception as track_error:  # noqa: BLE001
                        logger.error(f"Failed to track error: {track_error}")

                    if attempt <= max_retries and _should_retry(exc):
                        logger.warning(
                            f"{component}.{func.__name__} failed (attempt {attempt}/{max_retries + 1}): {exc}. "
                            f"Retrying in {retry_delay}s..."
                        )
                        await asyncio.sleep(retry_delay)
                        continue

                    logger.error(
                        f"{component}.{func.__name__} failed permanently after {attempt} attempts: {exc}",
                        exc_info=error_severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL],
                    )

                    if fallback_value is not None:
                        logger.info(
                            f"{component}.{func.__name__} returning fallback value: {fallback_value}"
                        )
                        return fallback_value

                    if last_error is not None:
                        raise last_error
                    raise RuntimeError(
                        f"{component}.{func.__name__} failed but no exception captured"
                    )

        return wrapper

    return decorator


def performance_monitor(
    component: str,
    warn_threshold: float = 5.0,
    critical_threshold: float = 10.0,
    log_slow_queries: bool = True,
) -> Callable[[CallableAsync], CallableAsync]:
    """Monitor function performance and log slow operations."""

    def decorator(func: CallableAsync) -> CallableAsync:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()

            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                execution_time = time.time() - start_time

                if execution_time >= critical_threshold:
                    logger.critical(
                        f"{component}.{func.__name__} CRITICAL SLOW: {execution_time:.3f}s "
                        f"(threshold: {critical_threshold}s)"
                    )
                elif execution_time >= warn_threshold:
                    logger.warning(
                        f"{component}.{func.__name__} slow: {execution_time:.3f}s "
                        f"(threshold: {warn_threshold}s)"
                    )
                elif log_slow_queries:
                    logger.debug(f"{component}.{func.__name__} completed in {execution_time:.3f}s")

                return result

            except Exception as exc:  # noqa: BLE001
                execution_time = time.time() - start_time
                logger.error(
                    f"{component}.{func.__name__} failed after {execution_time:.3f}s: {exc}"
                )
                raise

        return wrapper

    return decorator


def _should_retry(error: Exception) -> bool:
    """Determine if an error should trigger a retry."""

    no_retry_errors: Tuple[type[Exception], ...] = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        AssertionError,
    )
    retry_errors: Tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    if isinstance(error, no_retry_errors):
        return False

    if isinstance(error, retry_errors):
        return True

    error_msg = str(error).lower()
    temporary_indicators = (
        "timeout",
        "connection",
        "network",
        "temporary",
        "rate limit",
        "server error",
        "5xx",
        "unavailable",
    )

    return any(indicator in error_msg for indicator in temporary_indicators)


def _sanitize_args(args: Tuple[Any, ...], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Sanitize function arguments for logging (remove sensitive data)."""

    sensitive_keys = {
        "password",
        "private_key",
        "secret",
        "token",
        "api_key",
        "auth",
        "authorization",
        "key",
        "wallet",
    }

    sanitized: Dict[str, Any] = {}

    if args:
        sanitized["args"] = [
            "***REDACTED***"
            if isinstance(arg, str) and any(key in str(arg).lower() for key in sensitive_keys)
            else str(arg)[:100] + "..."
            if isinstance(arg, str) and len(str(arg)) > 100
            else str(type(arg).__name__)
            if not isinstance(arg, (str, int, float, bool, list, dict))
            else arg
            for arg in args
        ]

    if kwargs:
        sanitized["kwargs"] = {
            k: "***REDACTED***"
            if k.lower() in sensitive_keys
            or (isinstance(v, str) and any(key in k.lower() for key in sensitive_keys))
            else str(v)[:100] + "..."
            if isinstance(v, str) and len(str(v)) > 100
            else str(type(v).__name__)
            if not isinstance(v, (str, int, float, bool, list, dict))
            else v
            for k, v in kwargs.items()
        }

    return sanitized


def _sanitize_result(result: Any) -> Any:
    """Sanitize function result for logging."""

    if isinstance(result, dict):
        sensitive_keys = {"private_key", "secret", "token", "password", "key"}
        if any(key.lower() in str(result).lower() for key in sensitive_keys):
            return f"<dict with {len(result)} keys - potentially sensitive>"
        return {
            k: str(v)[:50] + "..." if isinstance(v, str) and len(str(v)) > 50 else v
            for k, v in list(result.items())[:5]
        }

    if isinstance(result, str) and len(result) > 100:
        return result[:100] + "..."

    if isinstance(result, (list, tuple)) and len(result) > 5:
        return f"<{type(result).__name__} with {len(result)} items>"

    return result
