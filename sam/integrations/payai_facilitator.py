"""PayAI x402 Facilitator integration."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from aiohttp import ClientConnectorError, ClientError
from spl.token.constants import (
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
)
from spl.token.instructions import (
    TransferCheckedParams,
    get_associated_token_address,
    transfer_checked,
)
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.null_signer import NullSigner

from ..core.tools import Tool, ToolSpec
from ..utils.http_client import get_session
from .solana.solana_tools import SolanaTools
from urllib.parse import urlparse


DEFAULT_SOLANA_RESOURCE = "https://x402.payai.network/api/solana/paid-content"

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
    default_network: Optional[str] = None

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

    def __init__(
        self,
        base_url: Optional[str],
        *,
        api_key: Optional[str] = None,
        default_network: Optional[str] = None,
        solana_tools: Optional[SolanaTools] = None,
    ) -> None:
        config = PayAIFacilitatorConfig(
            base_url=_normalize_url(base_url),
            api_key=(api_key or None),
            default_network=(default_network or None),
        )
        self._client = PayAIFacilitatorClient(config)
        self._default_network = (default_network or "").strip().lower() or None
        self._solana_tools = solana_tools

    @property
    def is_configured(self) -> bool:
        return self._client.is_configured

    @property
    def default_network(self) -> Optional[str]:
        return self._default_network

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

        if self.default_network:
            payment_requirements.setdefault("network", self.default_network)
            if isinstance(payment_payload, dict):
                payment_payload.setdefault("network", self.default_network)

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

        if self.default_network:
            payment_requirements.setdefault("network", self.default_network)
            if isinstance(payment_payload, dict):
                payment_payload.setdefault("network", self.default_network)

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

        # Prefer curated Echo resources for demo stability
        if self.default_network == "solana":
            return await self._curated_echo_resources()

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
            result = await self._client.discover(params)
            if self.default_network and isinstance(result, dict):
                items = result.get("items")
                if isinstance(items, list):
                    filtered: List[Dict[str, Any]] = []
                    for item in items:
                        accepts = item.get("accepts")
                        if not isinstance(accepts, list):
                            filtered.append(item)
                            continue
                        has_network = any(
                            str(req.get("network", "")).lower() == self.default_network
                            for req in accepts
                        )
                        if has_network:
                            filtered.append(item)
                    result["items"] = filtered or items
            return result
        except PayAIFacilitatorError as exc:
            return {"error": str(exc)}

    async def get_payment_requirements(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Locate payment requirements for a resource, preferring the default network."""
        if not self.is_configured:
            return {
                "error": "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL or update settings."
            }

        resource = args.get("resource")
        if not isinstance(resource, str) or not resource:
            resource = DEFAULT_SOLANA_RESOURCE
        parsed = urlparse(resource)
        if parsed.netloc != "x402.payai.network":
            resource = DEFAULT_SOLANA_RESOURCE

        discovered = await self.discover_resources({"type": "http", "limit": 50})
        if "error" in discovered:
            return discovered

        items = discovered.get("items") or []
        matches = [item for item in items if str(item.get("resource")) == resource]

        accepts: List[Dict[str, Any]] = []
        if matches:
            for item in matches:
                maybe_accepts = item.get("accepts") or []
                if isinstance(maybe_accepts, list):
                    accepts.extend(maybe_accepts)

        if not accepts:
            fallback = await self._fetch_requirements_from_resource(resource)
            if "error" in fallback:
                return fallback
            accepts = fallback.get("accepts", [])
            if not accepts:
                return {"error": f"No payment requirements available for resource '{resource}'"}

        requirement = accepts[0]
        if self.default_network:
            network_matches = [
                req
                for req in accepts
                if str(req.get("network", "")).lower() == self.default_network
            ]
            if network_matches:
                requirement = network_matches[0]

        return {
            "resource": resource,
            "network": requirement.get("network"),
            "payment_requirements": requirement,
        }

    async def pay_resource(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Automate the full x402 payment flow for Solana resources."""
        if not self.is_configured:
            return {
                "error": "PayAI facilitator URL is not configured. Set PAYAI_FACILITATOR_URL or update settings."
            }
        if not self._solana_tools or not getattr(self._solana_tools, "keypair", None):
            return {
                "error": "Solana wallet not available for automated payments",
                "help": "Import or configure a Solana private key before running auto-pay.",
            }

        resource = args.get("resource")
        if not isinstance(resource, str) or not resource:
            resource = DEFAULT_SOLANA_RESOURCE
        parsed_resource = urlparse(resource)
        if parsed_resource.netloc != "x402.payai.network":
            resource = DEFAULT_SOLANA_RESOURCE

        manual_requirements = args.get("payment_requirements")
        if isinstance(manual_requirements, dict):
            requirements = dict(manual_requirements)
            network = str(requirements.get("network") or self.default_network or "").lower()
        else:
            req_lookup = await self.get_payment_requirements({"resource": resource})
            if "error" in req_lookup:
                return req_lookup
            requirements = req_lookup.get("payment_requirements") or {}
            network = str(req_lookup.get("network") or self.default_network or "").lower()

        if network != "solana":
            return {
                "error": f"Automated payments currently support only Solana network. Requirement network: {requirements.get('network')}",
                "payment_requirements": requirements,
            }

        scheme = str(requirements.get("scheme") or "exact")
        asset = requirements.get("asset")
        pay_to = requirements.get("payTo")
        amount_str = requirements.get("maxAmountRequired")
        extra = requirements.get("extra") or {}

        if not asset or not pay_to or not amount_str:
            return {
                "error": "Payment requirements missing required fields (asset, payTo, maxAmountRequired)",
                "payment_requirements": requirements,
            }

        requirements.setdefault("network", "solana")
        requirements.setdefault("scheme", scheme)

        try:
            amount = int(amount_str)
        except (TypeError, ValueError):
            return {
                "error": f"Invalid maxAmountRequired value: {amount_str}",
                "payment_requirements": requirements,
            }

        transaction_result = await self._build_solana_payment_transaction(
            asset=asset,
            destination=pay_to,
            amount=amount,
            fee_payer=extra.get("feePayer") or pay_to,
        )

        if "error" in transaction_result:
            return {
                "error": transaction_result["error"],
                "payment_requirements": requirements,
            }

        payment_payload = {
            "x402Version": 1,
            "scheme": scheme,
            "network": "solana",
            "payload": {"transaction": transaction_result["transaction"]},
        }

        verification = await self.verify_payment(
            {"payment_payload": payment_payload, "payment_requirements": requirements}
        )
        if "error" in verification:
            return {
                "error": verification["error"],
                "payment_payload": payment_payload,
                "payment_requirements": requirements,
                "verification": verification,
            }

        settlement = await self.settle_payment(
            {"payment_payload": payment_payload, "payment_requirements": requirements}
        )
        result: Dict[str, Any] = {
            "payment_payload": payment_payload,
            "payment_requirements": requirements,
            "verification": verification,
            "settlement": settlement,
        }
        if "error" in settlement:
            result["error"] = settlement["error"]
        else:
            result["success"] = bool(settlement.get("settlement", settlement).get("success", False))
        return result

    async def _build_solana_payment_transaction(
        self, *, asset: str, destination: str, amount: int, fee_payer: str
    ) -> Dict[str, Any]:
        """Create a base64-encoded Solana transaction for the facilitator."""
        assert self._solana_tools is not None  # checked earlier
        keypair = getattr(self._solana_tools, "keypair", None)
        if keypair is None:
            return {"error": "Missing Solana keypair"}

        client = await getattr(self._solana_tools, "_get_client")()
        try:
            mint_pubkey = Pubkey.from_string(asset)
            owner_pubkey = keypair.pubkey()
            destination_pubkey = Pubkey.from_string(destination)
            fee_payer_pubkey = Pubkey.from_string(fee_payer)
        except Exception as exc:  # pragma: no cover - defensive validation
            return {"error": f"Invalid Solana address in payment requirements: {exc}"}

        # Fetch mint info to determine token program and decimals
        mint_info = await client.get_account_info(mint_pubkey)
        if not mint_info or not mint_info.value:
            return {"error": f"Mint account not found for asset {asset}"}

        token_program_owner = getattr(mint_info.value, "owner", None)
        token_program_str = str(token_program_owner) if token_program_owner is not None else ""

        if token_program_str == str(TOKEN_PROGRAM_ID):
            program_id = TOKEN_PROGRAM_ID
        elif token_program_str == str(TOKEN_2022_PROGRAM_ID):
            program_id = TOKEN_2022_PROGRAM_ID
        else:
            return {
                "error": f"Unsupported token program for asset {asset}: {token_program_str or 'unknown'}"
            }

        supply_resp = await client.get_token_supply(mint_pubkey)
        try:
            decimals = int(supply_resp.value.decimals)  # type: ignore[attr-defined]
        except Exception:
            decimals = 9

        payer_ata = get_associated_token_address(owner_pubkey, mint_pubkey, program_id)
        payer_account_info = await client.get_account_info(payer_ata)
        if not payer_account_info or not payer_account_info.value:
            return {
                "error": "Payer associated token account not found for required asset",
                "help": "Ensure the wallet holds the required token and the associated account exists.",
            }

        balance_resp = await client.get_token_account_balance(payer_ata)
        try:
            current_amount = int(balance_resp.value.amount)  # type: ignore[attr-defined]
        except Exception:
            current_amount = 0
        if current_amount < amount:
            return {
                "error": "Insufficient balance for payment requirement",
                "details": {
                    "required_amount": amount,
                    "available_amount": current_amount,
                },
            }

        instructions = []

        dest_account_info = await client.get_account_info(destination_pubkey)
        if not dest_account_info or not dest_account_info.value:
            return {
                "error": "Destination token account not found for provided payTo address",
                "details": {"pay_to": destination},
            }

        dest_owner = getattr(dest_account_info.value, "owner", None)
        if str(dest_owner) != str(program_id):
            return {
                "error": "Destination account is not owned by the expected token program",
                "details": {
                    "pay_to": destination,
                    "expected_program": str(program_id),
                    "actual_program": str(dest_owner) if dest_owner else None,
                },
            }

        # Build transfer instruction
        transfer_ix = transfer_checked(
            TransferCheckedParams(
                program_id=program_id,
                source=payer_ata,
                mint=mint_pubkey,
                dest=destination_pubkey,
                owner=owner_pubkey,
                amount=amount,
                decimals=decimals,
                signers=[],
            )
        )
        instructions.append(transfer_ix)

        # Prepare transaction with facilitator fee payer
        latest_blockhash = await client.get_latest_blockhash()
        blockhash = latest_blockhash.value.blockhash

        # Create a versioned transaction as required by x402 spec
        message = MessageV0.try_compile(
            payer=fee_payer_pubkey,
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )

        # Log transaction details for debugging
        logger.info(f"Transaction message: {len(message.instructions)} instructions")
        logger.info(f"Fee payer: {fee_payer_pubkey}")
        logger.info(f"Owner (signer): {owner_pubkey}")

        # Partially sign: NullSigner for fee payer (facilitator will sign later)
        # and real signature from user as token owner
        signers = (NullSigner(fee_payer_pubkey), keypair)
        transaction = VersionedTransaction(message, signers)

        serialized = bytes(transaction)
        encoded = base64.b64encode(serialized).decode("utf-8")

        logger.info(f"Transaction size: {len(serialized)} bytes")
        logger.info(f"Number of signatures: {len(transaction.signatures)}")

        return {"transaction": encoded, "recent_blockhash": str(blockhash)}

    async def _curated_echo_resources(self) -> Dict[str, Any]:
        """Return a predictable list of Echo resources for demo purposes."""
        accepts: List[Dict[str, Any]] = []
        fallback = await self._fetch_requirements_from_resource(DEFAULT_SOLANA_RESOURCE)
        if "error" not in fallback:
            accepts = fallback.get("accepts", [])

        item = {
            "resource": DEFAULT_SOLANA_RESOURCE,
            "type": "http",
            "description": "Echo Merchant Solana paid content (refunded)",
            "accepts": accepts,
        }
        return {"items": [item], "x402Version": 1}

    async def _fetch_requirements_from_resource(self, resource: str) -> Dict[str, Any]:
        """Fallback: request the resource directly to obtain 402 payment requirements."""
        session = await get_session()
        try:
            async with session.get(resource) as response:
                if response.status != 402:
                    return {
                        "error": f"Resource '{resource}' did not return 402 Payment Required (status {response.status})"
                    }
                try:
                    data = await response.json()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Failed to parse payment requirements from %s: %s", resource, exc)
                    return {"error": f"Failed to parse payment requirements from resource: {exc}"}
                accepts = data.get("accepts") or []
                if not isinstance(accepts, list) or not accepts:
                    return {
                        "error": f"Resource '{resource}' did not provide any payment requirements",
                        "details": data,
                    }
                return {"resource": resource, "accepts": accepts}
        except ClientConnectorError as exc:
            host = urlparse(resource).netloc or resource
            logger.error("DNS/connectivity error reaching resource %s: %s", resource, exc)
            return {
                "error": f"Could not reach '{host}' while fetching payment requirements.",
                "details": str(exc),
            }
        except ClientError as exc:
            logger.error("HTTP error fetching payment requirements from %s: %s", resource, exc)
            return {"error": f"HTTP error contacting resource '{resource}': {exc}"}
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "Unexpected error fetching payment requirements from %s: %s", resource, exc
            )
            return {"error": f"Failed to contact resource '{resource}': {exc}"}


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

    async def handle_requirements(args: Dict[str, Any]) -> Dict[str, Any]:
        return await tools.get_payment_requirements(args)

    async def handle_auto_pay(args: Dict[str, Any]) -> Dict[str, Any]:
        return await tools.pay_resource(args)

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
        Tool(
            spec=ToolSpec(
                name="payai_get_payment_requirements",
                description="Fetch payment requirements for a resource, defaulting to the configured facilitator network.",
                namespace="payai_facilitator",
                input_schema={
                    "type": "object",
                    "properties": {
                        "resource": {
                            "type": "string",
                            "description": "Resource URL (as provided by discovery).",
                        }
                    },
                    "required": ["resource"],
                },
            ),
            handler=handle_requirements,
        ),
        Tool(
            spec=ToolSpec(
                name="payai_auto_pay_resource",
                description="Fetch requirements, craft the Solana payment, verify, and settle via the PayAI facilitator.",
                namespace="payai_facilitator",
                input_schema={
                    "type": "object",
                    "properties": {
                        "resource": {
                            "type": "string",
                            "description": "Resource URL to purchase (defaults to facilitator discovery).",
                        },
                        "payment_requirements": {
                            "type": "object",
                            "description": "Optional pre-fetched payment requirements to skip discovery.",
                        },
                    },
                    "required": ["resource"],
                },
            ),
            handler=handle_auto_pay,
        ),
    ]
