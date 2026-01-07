"""Coinbase x402 facilitator integration for HTTP payment resources."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qsl, urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from ..core.tools import Tool, ToolSpec

try:  # pragma: no cover - optional dependency
    from x402.facilitator import FacilitatorClient, FacilitatorConfig  # type: ignore[import-untyped]
    from x402.types import (  # type: ignore[import-untyped]
        ListDiscoveryResourcesRequest,
        PaymentPayload,
        PaymentRequirements,
        SettleResponse,
        VerifyResponse,
    )
    from x402.clients.httpx import x402HttpxClient  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    FacilitatorClient = None  # type: ignore[assignment]
    FacilitatorConfig = Dict[str, Any]  # type: ignore[assignment]
    ListDiscoveryResourcesRequest = None  # type: ignore[assignment]
    PaymentPayload = None  # type: ignore[assignment]
    PaymentRequirements = None  # type: ignore[assignment]
    SettleResponse = None  # type: ignore[assignment]
    VerifyResponse = None  # type: ignore[assignment]
    x402HttpxClient = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class DiscoveryInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    type: Optional[str] = Field(
        default="http",
        description="Resource type filter (currently only 'http' is supported by facilitators).",
    )

    model_config = ConfigDict(extra="forbid")


class VerifyInput(BaseModel):
    payment_payload: Dict[str, Any] = Field(alias="paymentPayload")
    payment_requirements: Dict[str, Any] = Field(alias="paymentRequirements")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SettleInput(VerifyInput):
    pass


class AutoPayInput(BaseModel):
    url: HttpUrl = Field(description="Full URL to the x402-protected resource.")
    method: str = Field(default="GET", description="HTTP method to execute.")
    query: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional query parameters."
    )
    headers: Optional[Dict[str, str]] = Field(default=None, description="Extra request headers.")
    json_body: Optional[Dict[str, Any]] = Field(
        default=None, alias="json", description="JSON payload for the request."
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None, description="Form data payload (used if json not provided)."
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CoinbaseX402Tools:
    """High level wrappers to interact with Coinbase-operated x402 facilitator and resources."""

    def __init__(
        self,
        facilitator: Optional[Any],
        account: Optional[Any],
        *,
        client_factory: Optional[Callable[[Any, str, Optional[float]], Any]] = None,
        request_timeout: Optional[float] = None,
    ) -> None:
        self._facilitator = facilitator
        self._account = account
        self._client_factory = client_factory
        self._timeout = request_timeout

    @property
    def facilitator_ready(self) -> bool:
        return self._facilitator is not None and ListDiscoveryResourcesRequest is not None

    @property
    def has_wallet(self) -> bool:
        return self._account is not None

    async def list_resources(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.facilitator_ready:
            return {
                "error": (
                    "x402 facilitator client not available. Install the 'x402' package and "
                    "configure COINBASE_X402_FACILITATOR_URL."
                )
            }
        try:
            params = DiscoveryInput(**args)
        except ValidationError as exc:
            return {"error": f"Validation failed: {exc}"}

        request = ListDiscoveryResourcesRequest(**params.model_dump(by_alias=True))  # type: ignore[misc]

        try:
            response = await self._facilitator.list(request)  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover - network/runtime errors
            logger.error("Coinbase x402 discovery failed: %s", exc)
            return {"error": str(exc)}

        return json.loads(response.model_dump_json())  # type: ignore[union-attr]

    async def verify_payment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.facilitator_ready or PaymentPayload is None or PaymentRequirements is None:
            return {
                "error": (
                    "x402 facilitator client not available. Install the 'x402' package and "
                    "configure COINBASE_X402_FACILITATOR_URL."
                )
            }
        try:
            payload = VerifyInput(**args)
        except ValidationError as exc:
            return {"error": f"Validation failed: {exc}"}

        payment_payload = PaymentPayload(**payload.payment_payload)  # type: ignore[operator]
        payment_requirements = PaymentRequirements(**payload.payment_requirements)  # type: ignore[operator]

        try:
            result: VerifyResponse = await self._facilitator.verify(  # type: ignore[union-attr]
                payment_payload, payment_requirements
            )
        except Exception as exc:  # pragma: no cover
            logger.error("x402 verify request failed: %s", exc)
            return {"error": str(exc)}

        return json.loads(result.model_dump_json())  # type: ignore[union-attr]

    async def settle_payment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.facilitator_ready or PaymentPayload is None or PaymentRequirements is None:
            return {
                "error": (
                    "x402 facilitator client not available. Install the 'x402' package and "
                    "configure COINBASE_X402_FACILITATOR_URL."
                )
            }
        try:
            payload = SettleInput(**args)
        except ValidationError as exc:
            return {"error": f"Validation failed: {exc}"}

        payment_payload = PaymentPayload(**payload.payment_payload)  # type: ignore[operator]
        payment_requirements = PaymentRequirements(**payload.payment_requirements)  # type: ignore[operator]

        try:
            result: SettleResponse = await self._facilitator.settle(  # type: ignore[union-attr]
                payment_payload, payment_requirements
            )
        except Exception as exc:  # pragma: no cover
            logger.error("x402 settle request failed: %s", exc)
            return {"error": str(exc)}

        return json.loads(result.model_dump_json())  # type: ignore[union-attr]

    async def auto_pay(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if x402HttpxClient is None and self._client_factory is None:
            return {
                "error": "x402 HTTP client not available. Install the 'x402' package to enable auto-pay."
            }
        if not self.has_wallet:
            return {
                "error": "AIXBT/X402 private key not configured. Store an EVM private key to authorize payments."
            }
        try:
            payload = AutoPayInput(**args)
        except ValidationError as exc:
            return {"error": f"Validation failed: {exc}"}

        parsed = urlparse(str(payload.url))
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"
        params = dict(parse_qsl(parsed.query))
        if payload.query:
            params.update(payload.query)

        headers = dict(payload.headers or {})

        client_ctx = (
            self._client_factory(self._account, base_url, self._timeout)
            if self._client_factory is not None
            else x402HttpxClient(account=self._account, base_url=base_url, timeout=self._timeout)  # type: ignore[misc]
        )

        async with client_ctx as client:
            try:
                response = await client.request(  # type: ignore[union-attr]
                    payload.method.upper(),
                    path,
                    params=params or None,
                    headers=headers or None,
                    json=payload.json_body,
                    data=payload.data if payload.json_body is None else None,
                )
            except Exception as exc:  # pragma: no cover
                logger.error("x402 auto-pay request failed: %s", exc)
                return {"error": str(exc)}

        body: Any
        payment_info: Optional[Dict[str, Any]] = None
        try:
            body = response.json()
        except Exception:
            try:
                body = response.text
            except Exception:
                body = None

        header_val = response.headers.get("x-payment-response")
        if header_val:
            payment_info = _decode_payment_header(header_val)

        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "payment_response": payment_info,
        }


def _decode_payment_header(header: str) -> Dict[str, Any]:
    try:
        decoded = base64.b64decode(header)
        text = decoded.decode("utf-8")
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # pragma: no cover - best-effort decoding
        logger.debug("Failed to decode x-payment-response header: %s", header, exc_info=True)
    return {"raw": header}


def create_coinbase_x402_tools(tools: CoinbaseX402Tools) -> list[Tool]:
    return [
        Tool(
            spec=ToolSpec(
                name="coinbase_x402_list_resources",
                description="List discovery resources from the Coinbase x402 facilitator.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "description": "Maximum number of discovery items to return (default 20).",
                        },
                        "offset": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Offset for pagination.",
                        },
                        "type": {
                            "type": "string",
                            "description": "Discovery resource type (defaults to 'http').",
                        },
                    },
                },
                namespace="coinbase_x402",
            ),
            handler=tools.list_resources,
        ),
        Tool(
            spec=ToolSpec(
                name="coinbase_x402_verify_payment",
                description="Verify an x402 payment payload using the Coinbase facilitator.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "payment_payload": {
                            "type": "object",
                            "description": "Decoded x402 payment payload from the client (JSON).",
                        },
                        "payment_requirements": {
                            "type": "object",
                            "description": "Payment requirements returned by the resource.",
                        },
                    },
                    "required": ["payment_payload", "payment_requirements"],
                },
                namespace="coinbase_x402",
            ),
            handler=tools.verify_payment,
        ),
        Tool(
            spec=ToolSpec(
                name="coinbase_x402_settle_payment",
                description="Settle an x402 payment via the Coinbase facilitator.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "payment_payload": {
                            "type": "object",
                            "description": "Decoded x402 payment payload from the client (JSON).",
                        },
                        "payment_requirements": {
                            "type": "object",
                            "description": "Payment requirements returned by the resource.",
                        },
                    },
                    "required": ["payment_payload", "payment_requirements"],
                },
                namespace="coinbase_x402",
            ),
            handler=tools.settle_payment,
        ),
        Tool(
            spec=ToolSpec(
                name="coinbase_x402_auto_pay",
                description="Fetch a protected resource and automatically fulfill x402 payments using the configured EVM wallet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full resource URL (https://...).",
                        },
                        "method": {
                            "type": "string",
                            "description": "HTTP method to execute (default GET).",
                        },
                        "query": {"type": "object", "description": "Additional query parameters."},
                        "headers": {"type": "object", "description": "Extra request headers."},
                        "json": {"type": "object", "description": "JSON body payload if needed."},
                        "data": {"type": "object", "description": "Form data payload if needed."},
                    },
                    "required": ["url"],
                },
                namespace="coinbase_x402",
            ),
            handler=tools.auto_pay,
        ),
    ]
