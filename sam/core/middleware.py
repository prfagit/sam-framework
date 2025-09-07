import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Context for tool calls (extensible without breaking callers)."""

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


ToolCall = Callable[[Dict[str, Any], Optional[ToolContext]], Awaitable[Dict[str, Any]]]


class Middleware(Protocol):
    """Middleware interface using wrap-style composition.

    Implement wrap(name, call_next) returning a ToolCall that may perform
    pre/post/error handling and call the next function in the chain.
    """

    def wrap(self, name: str, call_next: ToolCall) -> ToolCall:  # pragma: no cover - interface
        ...


class LoggingMiddleware:
    def __init__(
        self,
        include_args: bool = False,
        include_result: bool = False,
        only: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
    ):
        self.include_args = include_args
        self.include_result = include_result
        self.only = only
        self.exclude = exclude

    def wrap(self, name: str, call_next: ToolCall) -> ToolCall:
        async def _call(args: Dict[str, Any], ctx: Optional[ToolContext]) -> Dict[str, Any]:
            if self.only and name not in self.only:
                return await call_next(args, ctx)
            if self.exclude and name in self.exclude:
                return await call_next(args, ctx)
            start = time.time()
            if self.include_args:
                logger.debug(f"Tool {name} start args={args}")
            else:
                logger.debug(f"Tool {name} start")
            try:
                result = await call_next(args, ctx)
                dur = time.time() - start
                if self.include_result:
                    logger.debug(f"Tool {name} ok in {dur:.3f}s result={result}")
                else:
                    logger.debug(f"Tool {name} ok in {dur:.3f}s")
                return result
            except Exception as e:
                dur = time.time() - start
                logger.error(f"Tool {name} failed in {dur:.3f}s: {e}")
                raise

        return _call


class RetryMiddleware:
    def __init__(
        self,
        max_retries: int = 2,
        base_delay: float = 0.25,
        only: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.only = only
        self.exclude = exclude

    def wrap(self, name: str, call_next: ToolCall) -> ToolCall:
        async def _call(args: Dict[str, Any], ctx: Optional[ToolContext]) -> Dict[str, Any]:
            if self.only and name not in self.only:
                return await call_next(args, ctx)
            if self.exclude and name in self.exclude:
                return await call_next(args, ctx)
            attempt = 0
            last_exc: Optional[Exception] = None
            while attempt <= self.max_retries:
                try:
                    return await call_next(args, ctx)
                except Exception as e:
                    last_exc = e
                    if attempt == self.max_retries:
                        break
                    delay = self.base_delay * (2**attempt)
                    await asyncio.sleep(delay)
                    attempt += 1
            # Exhausted retries
            assert last_exc is not None
            raise last_exc

        return _call


class RateLimitMiddleware:
    """Rate limiting using the shared rate limiter utility.

    If blocked, returns a normalized error-like dict; ToolRegistry will
    finalize normalization (success=False, error_detail, etc.).
    """

    def __init__(
        self,
        limit_type_fn: Optional[Callable[[str], str]] = None,
        identifier_fn: Optional[Callable[[str, Dict[str, Any], Optional[ToolContext]], str]] = None,
        only: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
    ):
        self.limit_type_fn = limit_type_fn or (lambda name: name)
        self.identifier_fn = identifier_fn or (lambda name, args, ctx: f"{name}")
        self.only = only
        self.exclude = exclude

    def wrap(self, name: str, call_next: ToolCall) -> ToolCall:
        async def _call(args: Dict[str, Any], ctx: Optional[ToolContext]) -> Dict[str, Any]:
            if self.only and name not in self.only:
                return await call_next(args, ctx)
            if self.exclude and name in self.exclude:
                return await call_next(args, ctx)
            try:
                from ..utils.rate_limiter import check_rate_limit

                limit_type = self.limit_type_fn(name)
                identifier = self.identifier_fn(name, args, ctx)
                allowed, info = await check_rate_limit(identifier, limit_type)
                if not allowed:
                    return {
                        "error": (
                            f"Rate limit exceeded. Please wait {int(info.get('retry_after', 60))}s."
                        ),
                        "rate_limit_info": info,
                    }
            except Exception as e:
                # Fail-open but log, to avoid blocking tools due to limiter issues
                logger.warning(f"RateLimitMiddleware error: {e}")
            result = await call_next(args, ctx)
            try:
                if isinstance(result, dict) and "error" not in result:
                    result.setdefault(
                        "rate_limit_info",
                        {
                            "remaining": info.get("remaining", 0),
                            "limit": info.get("limit", 0),
                            "reset_time": info.get("reset_time", 0),
                        },
                    )
            except Exception:
                pass
            return result

        return _call
