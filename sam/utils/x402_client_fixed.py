"""
Fixed x402 HTTP client with proper timeout handling.

This module provides a workaround for a bug in the x402 Python SDK where
the payment retry mechanism creates a new AsyncClient without inheriting
the timeout from the parent client.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Dict, List, Optional

import httpx
from eth_account import Account
from httpx import Request, Response, Timeout
from x402.clients.base import (
    MissingRequestConfigError,
    PaymentError,
    PaymentSelectorCallable,
    x402Client,
)
from x402.types import x402PaymentRequiredResponse

logger = logging.getLogger(__name__)


class FixedHttpxHooks:
    """HttpxHooks with proper timeout handling for payment retries."""

    _RETRY_EXTENSION_KEY = "x402_retry_attempt"

    def __init__(
        self,
        client: x402Client,
        retry_timeout: float = 60.0,
        transport_client: Optional[httpx.AsyncClient] = None,
    ):
        self.client = client
        self._retry_timeout = retry_timeout
        self._transport_client = transport_client

    async def on_request(self, request: Request):
        """Handle request before it is sent."""
        # No-op; we only use the response hook. Kept for parity with x402 SDK.
        return None

    async def on_response(self, response: Response) -> Response:
        """Handle 402 Payment Required responses with proper timeout."""
        if response.status_code != 402:
            return response

        if not response.request:
            raise MissingRequestConfigError("Missing request configuration")

        request = response.request

        # Skip when we're handling the retry response itself.
        if request.extensions.get(self._RETRY_EXTENSION_KEY):
            request.extensions.pop(self._RETRY_EXTENSION_KEY, None)
            return response

        try:
            await response.aread()
        except Exception as exc:
            raise PaymentError("Failed to read 402 response payload") from exc

        try:
            data = response.json()
            payment_response = x402PaymentRequiredResponse(**data)
        except Exception as exc:
            raise PaymentError("Invalid x402 payment response payload") from exc

        selected_requirements = self.client.select_payment_requirements(
            payment_response.accepts
        )

        payment_header = self.client.create_payment_header(
            selected_requirements, payment_response.x402_version
        )

        logger.debug(
            "Retrying %s %s with x402 payment (network=%s timeout=%ss)",
            request.method,
            request.url,
            selected_requirements.network,
            self._retry_timeout,
        )

        # Ensure request body is buffered so we can resend it.
        try:
            await request.aread()
        except Exception as exc:
            raise PaymentError("Failed to buffer request body for x402 retry") from exc

        retry_headers = httpx.Headers(request.headers)
        retry_headers["X-Payment"] = payment_header
        retry_headers["Access-Control-Expose-Headers"] = "X-Payment-Response"

        body = request.content

        retry_extensions = dict(request.extensions or {})
        retry_extensions[self._RETRY_EXTENSION_KEY] = True
        retry_extensions["timeout"] = Timeout(self._retry_timeout).as_dict()

        retry_request = Request(
            request.method,
            request.url,
            headers=retry_headers,
            content=body if body else None,
            extensions=retry_extensions,
        )

        try:
            retry_response = await self._send_retry_request(retry_request)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise PaymentError(f"Failed to submit x402 payment retry: {exc}") from exc

        if retry_response.status_code == 402:
            error_detail = self._extract_payment_error(retry_response)
            raise PaymentError(
                error_detail or "x402 payment was rejected by the remote service"
            )

        # Copy retry response back into the original response instance.
        response.status_code = retry_response.status_code
        response.headers = retry_response.headers
        response._content = retry_response.content
        response._text = None
        response._encoding = retry_response.encoding
        response.extensions = retry_response.extensions
        response.request = retry_response.request
        response.request.extensions.pop(self._RETRY_EXTENSION_KEY, None)

        await retry_response.aclose()

        return response

    async def _send_retry_request(self, request: Request) -> Response:
        if self._transport_client is not None:
            return await self._transport_client.send(request)

        async with httpx.AsyncClient(timeout=self._retry_timeout) as client:
            return await client.send(request)

    @staticmethod
    def _extract_payment_error(response: Response) -> Optional[str]:
        header = response.headers.get("X-Payment-Response")
        if not header:
            return None
        try:
            decoded = base64.b64decode(header)
            payload = json.loads(decoded.decode("utf-8"))
        except Exception:
            logger.debug("Failed to decode x402 payment response header.", exc_info=True)
            return None

        if isinstance(payload, dict):
            return payload.get("error") or payload.get("message")
        if isinstance(payload, str):
            return payload
        return None


def fixed_x402_payment_hooks(
    account: Account,
    retry_timeout: float = 60.0,
    max_value: Optional[int] = None,
    payment_requirements_selector: Optional[PaymentSelectorCallable] = None,
    transport_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, List]:
    """Create httpx event hooks with proper timeout handling.

    Args:
        account: eth_account.Account for signing payments
        retry_timeout: Timeout for payment retry requests (default 60s)
        max_value: Optional maximum allowed payment amount
        payment_requirements_selector: Optional custom payment selector
        transport_client: Optional AsyncClient used for retry transport

    Returns:
        Dictionary of event hooks with fixed timeout handling
    """
    client = x402Client(
        account,
        max_value=max_value,
        payment_requirements_selector=payment_requirements_selector,
    )
    hooks = FixedHttpxHooks(
        client,
        retry_timeout=retry_timeout,
        transport_client=transport_client,
    )

    return {
        "request": [hooks.on_request],
        "response": [hooks.on_response],
    }


class FixedX402HttpxClient(httpx.AsyncClient):
    """AsyncClient with built-in x402 payment handling and proper timeout.
    
    The original x402HttpxClient creates a new AsyncClient() for payment retries
    without inheriting the timeout, causing ReadTimeout errors during on-chain
    payment settlement on networks like Base (which can take 30-60s).
    
    This client ensures the timeout is respected during payment retries.
    """
    
    def __init__(
        self,
        account: Account,
        retry_timeout: float = 60.0,
        max_value: Optional[int] = None,
        payment_requirements_selector: Optional[PaymentSelectorCallable] = None,
        **kwargs
    ):
        """Initialize with explicit retry timeout.

        Args:
            account: eth_account.Account for signing payments
            retry_timeout: Timeout for payment retry requests (default 60s for Base network)
            max_value: Optional maximum allowed payment amount
            payment_requirements_selector: Optional custom payment selector
            **kwargs: Additional arguments passed to AsyncClient
        """
        super().__init__(**kwargs)
        self.event_hooks = fixed_x402_payment_hooks(
            account,
            retry_timeout=retry_timeout,
            max_value=max_value,
            payment_requirements_selector=payment_requirements_selector,
            transport_client=self,
        )


def create_fixed_x402_client(
    account: Account,
    base_url: str,
    timeout: Optional[float] = None,
    **kwargs
) -> FixedX402HttpxClient:
    """Factory function to create a fixed x402 client.
    
    Args:
        account: eth_account.Account for signing payments
        base_url: Base URL for the API
        timeout: Request timeout (default 60s)
        **kwargs: Additional arguments passed to the client
        
    Returns:
        FixedX402HttpxClient instance
    """
    timeout = timeout if timeout is not None else 60.0
    
    return FixedX402HttpxClient(
        account=account,
        base_url=base_url,
        timeout=timeout,
        retry_timeout=timeout,
        **kwargs
    )
