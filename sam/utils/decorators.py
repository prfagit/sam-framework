import functools
import logging
from typing import Dict, Any, Callable, Optional
from .rate_limiter import check_rate_limit
from ..config.settings import Settings

logger = logging.getLogger(__name__)


def rate_limit(limit_type: str = "default", identifier_key: Optional[str] = None):
    """
    Decorator to add rate limiting to tool functions.
    
    Args:
        limit_type: Type of rate limit to apply (matches rate_limiter.py limits)
        identifier_key: Key from function args to use as identifier (defaults to "public_key" or "user_id")
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Dict[str, Any]:
            # Extract identifier from function arguments
            identifier = None
            
            # Check kwargs for identifier
            if identifier_key and identifier_key in kwargs:
                identifier = kwargs[identifier_key]
            elif "public_key" in kwargs:
                identifier = kwargs["public_key"]
            elif "user_id" in kwargs:
                identifier = kwargs["user_id"]
            
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
                    logger.warning(f"Rate limit exceeded for {func.__name__}: {identifier} ({limit_type})")
                    return {
                        "error": f"Rate limit exceeded. Please wait {info.get('retry_after', 60)} seconds before trying again.",
                        "rate_limit_info": info
                    }
                
                # Execute the original function
                result = await func(*args, **kwargs)
                
                # Add rate limit info to successful responses
                if isinstance(result, dict) and "error" not in result:
                    result["rate_limit_info"] = {
                        "remaining": info.get("remaining", 0),
                        "limit": info.get("limit", 0),
                        "reset_time": info.get("reset_time", 0)
                    }
                
                return result
                
            except Exception as e:
                logger.error(f"Rate limiter error in {func.__name__}: {e}")
                # On rate limiter error, execute function anyway but log the issue
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, backoff_factor: float = 2.0):
    """
    Decorator to add retry logic with exponential backoff for API calls.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        backoff_factor: Multiplier for delay on each retry
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Dict[str, Any]:
            import asyncio
            
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        delay = base_delay * (backoff_factor ** attempt)
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay:.1f}s")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed for {func.__name__}: {e}")
            
            # If we get here, all retries failed
            return {
                "error": f"Operation failed after {max_retries + 1} attempts: {str(last_exception)}",
                "retry_attempts": max_retries + 1
            }
        
        return wrapper
    return decorator


def log_execution(include_args: bool = False, include_result: bool = False):
    """
    Decorator to log function execution for debugging and monitoring.
    
    Args:
        include_args: Whether to log function arguments  
        include_result: Whether to log function result
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            import time
            
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


def validate_args(**validators):
    """
    Decorator to validate function arguments using custom validators.
    
    Args:
        **validators: Mapping of argument name to validator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Validate kwargs
            for arg_name, validator in validators.items():
                if arg_name in kwargs:
                    try:
                        validator(kwargs[arg_name])
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