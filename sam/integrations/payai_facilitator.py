"""PayAI x402 Facilitator integration."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from ..core.tools import Tool, ToolSpec
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)


class PayAIFacilitatorError(RuntimeError):
    """Raised for PayAI facilitator integration failures."""


def _normalize_url(value: Optional[str]) -> str:
    raw = (value or "").strip()
    return raw[:-1] if raw.endswith("/") else raw


def _flatten_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        flattened[f"metadata[{key}]"] = value
    return flattened


@dataclass
class PayAIFacilitatorConfig:
    base_url: str
    api_key: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)


class PayAIFacilitatorClient:
    """Async HTTP client for the PayAI facilitator endpoints."""

    def __init__(self, config: PayAIFacilitatorConfig) -> None:
        self._config = config

    @property
    def is_configured(self) -> bool:
        return self._config.is_configured

    async def verify(
        self, payment_payload: Dict[str, Any], payment_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await self._post(
            "/verify",
            {"paymentPayload": payment_payload, "paymentRequirements": payment_requirements},
        )

    async def settle(
        self, payment_payload: Dict[str, Any], payment_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await self._post(
            "/settle",
            {"paymentPayload": payment_payload, "paymentRequirements": payment_requirements},
        )

    async def supported(self) -> Dict[str, Any]:
        return await self._get("/supported")

    async def discover(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._get("/discovery/resources", params=params)

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", path, json_payload=payload)

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.is_configured:
            raise PayAIFacilitatorError(
                "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL."
            )

        session = await get_session()
        url = f"{self._config.base_url}{path}"
        headers: Dict[str, str] = {"Accept": "application/json"}
        if method.upper() in {"POST", "PUT", "PATCH"}:
            headers["Content-Type"] = "application/json"
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        async with session.request(
            method.upper(), url, json=json_payload, params=params or None, headers=headers
        ) as response:
            text = await response.text()
            if response.status >= 400:
                logger.error(
                    "PayAI facilitator request failed: %s %s [%s] %s",
                    method,
                    url,
                    response.status,
                    text,
                )
                raise PayAIFacilitatorError(
                    f"Facilitator request failed with status {response.status}: {text or 'unknown error'}"
                )

            if not text:
                return {}

            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                logger.error("Invalid JSON from PayAI facilitator: %s", text)
                raise PayAIFacilitatorError("Facilitator returned invalid JSON") from exc


class PayAIFacilitatorTools:
    """High-level tool wrappers for interacting with the PayAI facilitator."""

    def __init__(self, base_url: Optional[str], api_key: Optional[str] = None) -> None:
        config = PayAIFacilitatorConfig(
            base_url=_normalize_url(base_url),
            api_key=(api_key or None),
        )
        self._client = PayAIFacilitatorClient(config)

    @property
    def is_configured(self) -> bool:
        return self._client.is_configured

    async def verify_payment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_configured:
            return {
                "error": "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL or update settings."
            }

        payment_payload = args.get("payment_payload")
        payment_requirements = args.get("payment_requirements")
        if not isinstance(payment_payload, dict) or not isinstance(payment_requirements, dict):
            return {
                "error": "Both payment_payload and payment_requirements must be provided as objects."
            }

        try:
            result = await self._client.verify(payment_payload, payment_requirements)
            return {"verification": result}
        except PayAIFacilitatorError as exc:
            return {"error": str(exc)}

    async def settle_payment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_configured:
            return {
                "error": "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL or update settings."
            }

        payment_payload = args.get("payment_payload")
        payment_requirements = args.get("payment_requirements")
        if not isinstance(payment_payload, dict) or not isinstance(payment_requirements, dict):
            return {
                "error": "Both payment_payload and payment_requirements must be provided as objects."
            }

        try:
            result = await self._client.settle(payment_payload, payment_requirements)
            return {"settlement": result}
        except PayAIFacilitatorError as exc:
            return {"error": str(exc)}

    async def get_supported(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {
                "error": "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL or update settings."
            }

        try:
            return await self._client.supported()
        except PayAIFacilitatorError as exc:
            return {"error": str(exc)}

    async def discover_resources(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_configured:
            return {
                "error": "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL or update settings."
            }

        params: Dict[str, Any] = {}
        resource_type = args.get("resource_type") or args.get("type")
        if isinstance(resource_type, str) and resource_type:
            params["type"] = resource_type

        limit_value = args.get("limit")
        if limit_value is not None:
            try:
                limit = max(1, min(int(limit_value), 100))
                params["limit"] = limit
            except (TypeError, ValueError):
                return {"error": "limit must be an integer between 1 and 100"}

        offset_value = args.get("offset")
        if offset_value is not None:
            try:
                offset = max(0, int(offset_value))
                params["offset"] = offset
            except (TypeError, ValueError):
                return {"error": "offset must be a non-negative integer"}

        metadata = args.get("metadata")
        if isinstance(metadata, dict):
            params.update(_flatten_metadata(metadata))

        try:
            return await self._client.discover(params)
        except PayAIFacilitatorError as exc:
            return {"error": str(exc)}


def create_payai_facilitator_tools(tools: PayAIFacilitatorTools) -> list[Tool]:
    """Create Tool definitions for the PayAI facilitator integration."""

    class VerifyInput(BaseModel):
        payment_payload: Dict[str, Any] = Field(
            ...,
            description="x402 payment payload (decoded JSON) that the client supplied in the `X-PAYMENT` header.",
        )
        payment_requirements: Dict[str, Any] = Field(
            ...,
            description="Payment requirements object originally returned with the HTTP 402 response.",
        )

    class SettleInput(VerifyInput):
        """Reuses the same schema as verification."""

    class DiscoverInput(BaseModel):
        resource_type: Optional[str] = Field(
            None, description="Optional resource type filter (e.g., 'http')."
        )
        limit: Optional[int] = Field(
            20, ge=1, le=100, description="Maximum number of resources to return (1-100)."
        )
        offset: Optional[int] = Field(
            0, ge=0, description="Number of resources to skip for pagination."
        )
        metadata: Optional[Dict[str, Any]] = Field(
            default=None,
            description="Optional metadata filters, e.g., {'provider': 'Echo Merchant'}.",
        )

        @field_validator("limit")
        @classmethod
        def _validate_limit(cls, value: Optional[int]) -> Optional[int]:  # pragma: no cover
            if value is None:
                return None
            if not 1 <= value <= 100:
                raise ValueError("limit must be between 1 and 100")
            return value

        @field_validator("offset")
        @classmethod
        def _validate_offset(cls, value: Optional[int]) -> Optional[int]:  # pragma: no cover
            if value is None:
                return None
            if value < 0:
                raise ValueError("offset must be >= 0")
            return value

    async def handle_verify(args: Dict[str, Any]) -> Dict[str, Any]:
        return await tools.verify_payment(args)

    async def handle_settle(args: Dict[str, Any]) -> Dict[str, Any]:
        return await tools.settle_payment(args)

    async def handle_supported(_: Dict[str, Any]) -> Dict[str, Any]:
        return await tools.get_supported()

    async def handle_discover(args: Dict[str, Any]) -> Dict[str, Any]:
        return await tools.discover_resources(args)

    return [
        Tool(
            spec=ToolSpec(
                name="payai_verify_payment",
                description="Validate an x402 payment payload against the PayAI facilitator without settling it.",
                namespace="payai_facilitator",
                input_schema=VerifyInput.model_json_schema(),
            ),
            handler=handle_verify,
        ),
        Tool(
            spec=ToolSpec(
                name="payai_settle_payment",
                description="Settle an x402 payment through the PayAI facilitator and return settlement details.",
                namespace="payai_facilitator",
                input_schema=SettleInput.model_json_schema(),
            ),
            handler=handle_settle,
        ),
        Tool(
            spec=ToolSpec(
                name="payai_supported_networks",
                description="List schemes and networks supported by the configured PayAI facilitator.",
                namespace="payai_facilitator",
                input_schema={"type": "object", "properties": {}},
            ),
            handler=handle_supported,
        ),
        Tool(
            spec=ToolSpec(
                name="payai_discover_resources",
                description="Discover x402-enabled resources exposed by the facilitator Bazaar.",
                namespace="payai_facilitator",
                input_schema=DiscoverInput.model_json_schema(),
            ),
            handler=handle_discover,
        ),
    ]
