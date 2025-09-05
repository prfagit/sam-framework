"""Enhanced decorators for error handling, logging, and monitoring."""

import functools
import logging
import time
import traceback
import asyncio
from typing import Dict, Any, Callable
from .error_handling import get_error_tracker, ErrorSeverity

logger = logging.getLogger(__name__)


def safe_async_operation(
    component: str,
    error_severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    fallback_value: Any = None,
    log_args: bool = False,
    log_result: bool = False,
    max_retries: int = 0,
    retry_delay: float = 1.0
):
    """
    Enhanced decorator for safe async operations with comprehensive error handling.
    
    Args:
        component: Component name for error tracking
        error_severity: Severity level for error logging
        fallback_value: Value to return on error (if not None)
        log_args: Whether to log function arguments
        log_result: Whether to log function result
        max_retries: Maximum number of retries on failure
        retry_delay: Delay between retries in seconds
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            attempt = 0
            last_error = None
            
            # Log function call
            if log_args:
                safe_args = _sanitize_args(args, kwargs)
                logger.debug(f"{component}.{func.__name__} called with args: {safe_args}")
            else:
                logger.debug(f"{component}.{func.__name__} called")
            
            while attempt <= max_retries:
                try:
                    # Execute the function
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)
                    
                    # Log success
                    execution_time = time.time() - start_time
                    logger.debug(f"{component}.{func.__name__} completed in {execution_time:.3f}s")
                    
                    if log_result and result is not None:
                        safe_result = _sanitize_result(result)
                        logger.debug(f"{component}.{func.__name__} result: {safe_result}")
                    
                    return result
                    
                except Exception as e:
                    attempt += 1
                    last_error = e
                    execution_time = time.time() - start_time
                    
                    # Log the error
                    error_context = {
                        'function': func.__name__,
                        'component': component,
                        'attempt': attempt,
                        'max_retries': max_retries,
                        'execution_time': execution_time,
                        'error_type': type(e).__name__
                    }
                    
                    # Track error
                    try:
                        error_tracker = await get_error_tracker()
                        await error_tracker.log_error(
                            error_type=type(e).__name__,
                            error_message=str(e),
                            severity=error_severity,
                            component=component,
                            context=error_context,
                            stack_trace=traceback.format_exc() if error_severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL] else None
                        )
                    except Exception as track_error:
                        logger.error(f"Failed to track error: {track_error}")
                    
                    # Decide whether to retry
                    if attempt <= max_retries and _should_retry(e):
                        logger.warning(
                            f"{component}.{func.__name__} failed (attempt {attempt}/{max_retries + 1}): {e}. "
                            f"Retrying in {retry_delay}s..."
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.error(
                            f"{component}.{func.__name__} failed permanently after {attempt} attempts: {e}",
                            exc_info=error_severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]
                        )
                        
                        # Return fallback value if provided
                        if fallback_value is not None:
                            logger.info(f"{component}.{func.__name__} returning fallback value: {fallback_value}")
                            return fallback_value
                        
                        # Re-raise the last error
                        raise last_error
            
        return wrapper
    return decorator


def performance_monitor(
    component: str,
    warn_threshold: float = 5.0,
    critical_threshold: float = 10.0,
    log_slow_queries: bool = True
):
    """
    Monitor function performance and log slow operations.
    
    Args:
        component: Component name for logging
        warn_threshold: Warning threshold in seconds
        critical_threshold: Critical threshold in seconds
        log_slow_queries: Whether to log slow operations
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                execution_time = time.time() - start_time
                
                # Log performance metrics
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
                
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(
                    f"{component}.{func.__name__} failed after {execution_time:.3f}s: {e}"
                )
                raise
                
        return wrapper
    return decorator


def circuit_breaker_enhanced(
    component: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    expected_exceptions: tuple = (Exception,)
):
    """
    Enhanced circuit breaker with better error tracking and recovery.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            from .error_handling import get_circuit_breaker
            
            breaker = await get_circuit_breaker(
                component,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                expected_exception=expected_exceptions[0] if expected_exceptions else Exception
            )
            
            return await breaker.call(func, *args, **kwargs)
            
        return wrapper
    return decorator


def _should_retry(error: Exception) -> bool:
    """Determine if an error should trigger a retry."""
    # Don't retry on these error types
    no_retry_errors = (
        ValueError,  # Invalid input
        TypeError,   # Type errors
        KeyError,    # Missing keys
        AttributeError,  # Missing attributes
        AssertionError,  # Assertion failures
    )
    
    # Retry on network/temporary errors
    retry_errors = (
        ConnectionError,
        TimeoutError,
        OSError,  # Network issues
    )
    
    if isinstance(error, no_retry_errors):
        return False
    
    if isinstance(error, retry_errors):
        return True
    
    # Check error message for common temporary issues
    error_msg = str(error).lower()
    temporary_indicators = [
        'timeout', 'connection', 'network', 'temporary', 
        'rate limit', 'server error', '5xx', 'unavailable'
    ]
    
    return any(indicator in error_msg for indicator in temporary_indicators)


def _sanitize_args(args: tuple, kwargs: dict) -> Dict[str, Any]:
    """Sanitize function arguments for logging (remove sensitive data)."""
    sensitive_keys = {
        'password', 'private_key', 'secret', 'token', 'api_key', 
        'auth', 'authorization', 'key', 'wallet'
    }
    
    sanitized = {}
    
    # Sanitize positional args
    if args:
        sanitized['args'] = [
            '***REDACTED***' if isinstance(arg, str) and any(key in str(arg).lower() for key in sensitive_keys)
            else str(arg)[:100] + '...' if isinstance(arg, str) and len(str(arg)) > 100
            else str(type(arg).__name__) if not isinstance(arg, (str, int, float, bool, list, dict))
            else arg
            for arg in args
        ]
    
    # Sanitize keyword args
    if kwargs:
        sanitized['kwargs'] = {
            k: '***REDACTED***' if k.lower() in sensitive_keys or 
               (isinstance(v, str) and any(key in k.lower() for key in sensitive_keys))
            else str(v)[:100] + '...' if isinstance(v, str) and len(str(v)) > 100
            else str(type(v).__name__) if not isinstance(v, (str, int, float, bool, list, dict))
            else v
            for k, v in kwargs.items()
        }
    
    return sanitized


def _sanitize_result(result: Any) -> Any:
    """Sanitize function result for logging."""
    if isinstance(result, dict):
        # Check for sensitive keys in dictionary
        sensitive_keys = {'private_key', 'secret', 'token', 'password', 'key'}
        if any(key.lower() in str(result).lower() for key in sensitive_keys):
            return f"<dict with {len(result)} keys - potentially sensitive>"
        return {k: str(v)[:50] + '...' if isinstance(v, str) and len(str(v)) > 50 else v 
                for k, v in list(result.items())[:5]}  # Limit to first 5 items
    elif isinstance(result, str) and len(result) > 100:
        return result[:100] + '...'
    elif isinstance(result, (list, tuple)) and len(result) > 5:
        return f"<{type(result).__name__} with {len(result)} items>"
    else:
        return result