"""Solana Rent & Rug Shield non-custodial pre-buy token audit and empty ATA rent scanner."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import aiohttp
from pydantic import BaseModel, Field

from ..core.tools import Tool, ToolSpec

logger = logging.getLogger(__name__)

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SOLANA_PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEFAULT_RENTSHIELD_URL = "https://rentandrugshield.com"


def is_valid_solana_pubkey(address: str) -> bool:
    """Verify that input decodes to an exact 32-byte base58 Solana public key."""
    if not isinstance(address, str):
        return False
    cleaned = address.strip()
    if not SOLANA_PUBKEY_RE.match(cleaned):
        return False
    acc = [0]
    for ch in cleaned:
        carry = BASE58_ALPHABET.find(ch)
        if carry < 0:
            return False
        for idx in range(len(acc)):
            carry += acc[idx] * 58
            acc[idx] = carry & 0xFF
            carry >>= 8
        while carry > 0:
            acc.append(carry & 0xFF)
            carry >>= 8
    leading_ones = 0
    while leading_ones < len(cleaned) and cleaned[leading_ones] == "1":
        leading_ones += 1
    return len(acc) + leading_ones == 32


def validate_public_address(address: str, field_name: str = "address") -> str:
    """Validate public Solana address and reject private keys or seed phrases."""
    cleaned = str(address or "").strip()
    if not is_valid_solana_pubkey(cleaned):
        raise ValueError(
            f"Invalid {field_name}: expected a 32-byte base58 Solana public key. "
            "Never pass private keys or seed phrases."
        )
    return cleaned


class RentShieldTools:
    """Read-only client for Solana Rent & Rug Shield (https://rentandrugshield.com)."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        raw_url = api_url or os.environ.get("RENTSHIELD_API_URL") or ""
        cleaned_url = raw_url.strip().rstrip("/")
        self._explicit_base = (
            cleaned_url if cleaned_url and cleaned_url != DEFAULT_RENTSHIELD_URL else None
        )
        self.api_key = api_key or os.environ.get("RENTSHIELD_API_KEY") or None
        self.timeout_seconds = timeout_seconds
        self._cached_live_base: Optional[str] = None
        self._cached_expires_at: float = 0.0

    def reset_cache(self) -> None:
        self._cached_live_base = None
        self._cached_expires_at = 0.0

    async def _resolve_live_base(self, session: aiohttp.ClientSession) -> Optional[str]:
        now = time.monotonic()
        if self._cached_live_base and self._cached_expires_at > now:
            return self._cached_live_base
        async with session.get(
            f"{DEFAULT_RENTSHIELD_URL}/live_endpoint.json",
            headers={"Accept": "application/json"},
        ) as resp:
            if resp.status != 200:
                return None
            payload = await resp.json()
            candidate = (
                str(payload.get("api_base") or payload.get("endpoint") or "").strip().rstrip("/")
            )
            if not candidate:
                return None
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or not parsed.netloc:
                return None
            self._cached_live_base = candidate
            self._cached_expires_at = now + 300.0
            return candidate

    async def _request_json(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        req_headers: Dict[str, str] = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        if self.api_key:
            req_headers["X-API-Key"] = self.api_key

        initial_base = self._explicit_base or (
            self._cached_live_base
            if self._cached_live_base and self._cached_expires_at > time.monotonic()
            else DEFAULT_RENTSHIELD_URL
        )

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, f"{initial_base}{path}", headers=req_headers, json=json_body
            ) as resp:
                if not self._explicit_base and resp.status in (404, 405):
                    live_base = await self._resolve_live_base(session)
                    if live_base and live_base != initial_base:
                        async with session.request(
                            method, f"{live_base}{path}", headers=req_headers, json=json_body
                        ) as retry_resp:
                            if retry_resp.status >= 400:
                                raise RuntimeError(f"Rent & Rug Shield HTTP {retry_resp.status}")
                            return dict(await retry_resp.json())
                if resp.status >= 400:
                    raise RuntimeError(f"Rent & Rug Shield HTTP {resp.status}")
                return dict(await resp.json())

    async def check_token_rug_shield(self, mint: str) -> Dict[str, Any]:
        """Run a read-only 11-layer pre-buy rug and scam audit on a Solana token mint."""
        clean_mint = validate_public_address(mint, "mint")
        data = await self._request_json(
            "GET",
            f"/api/v1/shield-check?mint={quote(clean_mint, safe='')}",
            headers={"X-Payment-Protocol": "x402"},
        )
        score = data.get("score", data.get("safety_score"))
        safe_to_buy = data.get("safe_to_buy")
        if safe_to_buy is None:
            safe_to_buy = bool(
                isinstance(score, (int, float))
                and score >= 75
                and not data.get("hidden_pda_rent_trap")
            )
        return {
            "ok": bool(data.get("ok", True)),
            "mint": data.get("mint") or clean_mint,
            "symbol": data.get("symbol"),
            "name": data.get("name"),
            "token_program": data.get("token_program"),
            "score": score,
            "safe_to_buy": bool(safe_to_buy),
            "verdict": data.get("verdict"),
            "layers_checked": data.get("layers_checked", 11),
            "layers_passed": data.get("layers_passed"),
            "checklist_summary": data.get("checklist_summary"),
            "mint_authority_active": bool(data.get("mint_authority_active")),
            "freeze_authority_active": bool(data.get("freeze_authority_active")),
            "has_permanent_delegate": bool(data.get("has_permanent_delegate")),
            "has_transfer_hook": bool(data.get("has_transfer_hook")),
            "hidden_pda_rent_trap": bool(data.get("hidden_pda_rent_trap")),
            "checks": data.get("checks") if isinstance(data.get("checks"), list) else [],
            "report_url": f"{DEFAULT_RENTSHIELD_URL}/audit/{clean_mint}",
        }

    async def scan_wallet_unclaimed_rent(self, wallet: str) -> Dict[str, Any]:
        """Preview reclaimable SOL rent across empty SPL and Token-2022 ATAs (0% first-claim fee)."""
        clean_wallet = validate_public_address(wallet, "wallet")
        data = await self._request_json(
            "POST",
            "/api/scan-wallet",
            headers={"Content-Type": "application/json"},
            json_body={"wallet": clean_wallet, "user_initiated": False},
        )
        return {
            "ok": bool(data.get("ok", True)),
            "wallet": data.get("wallet") or clean_wallet,
            "is_first_free_claim": bool(data.get("is_first_free_claim")),
            "effective_fee_bps": data.get("effective_fee_bps", data.get("fee_bps", 0)),
            "reclaimable_count": data.get("reclaimable_count", 0),
            "empty_count": data.get("empty_count", 0),
            "dust_count": data.get("dust_count", 0),
            "active_count": data.get("active_count", 0),
            "total_reclaimable_sol": data.get("total_reclaimable_sol", 0.0),
            "total_reclaimable_lamports": data.get("total_reclaimable_lamports", 0),
            "empty_reclaimable": (
                data.get("empty_reclaimable")
                if isinstance(data.get("empty_reclaimable"), list)
                else []
            ),
            "dust_reclaimable": (
                data.get("dust_reclaimable")
                if isinstance(data.get("dust_reclaimable"), list)
                else []
            ),
            "claim_url": f"{DEFAULT_RENTSHIELD_URL}/?wallet={clean_wallet}",
        }


def create_rentshield_tools(rentshield_tools: RentShieldTools) -> List[Tool]:
    """Create SAM Tool instances for Solana Rent & Rug Shield."""

    class CheckTokenRugShieldInput(BaseModel):
        mint: str = Field(
            ...,
            description="Public Solana token mint address (base58). Never pass private keys.",
        )

    class ScanWalletRentInput(BaseModel):
        wallet: str = Field(
            ...,
            description="Public Solana wallet address (base58). Never pass private keys.",
        )

    async def handle_check_token(args: Dict[str, Any]) -> Dict[str, Any]:
        return await rentshield_tools.check_token_rug_shield(str(args.get("mint", "")))

    async def handle_scan_wallet(args: Dict[str, Any]) -> Dict[str, Any]:
        return await rentshield_tools.scan_wallet_unclaimed_rent(str(args.get("wallet", "")))

    return [
        Tool(
            spec=ToolSpec(
                name="check_token_rug_shield",
                description=(
                    "Run a read-only 11-layer pre-buy rug and scam safety check on a Solana "
                    "token mint (SPL, Token-2022, or pump.fun) via Rent & Rug Shield."
                ),
                input_schema={
                    "name": "check_token_rug_shield",
                    "description": "11-layer pre-buy Solana token rug check",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {
                                "type": "string",
                                "description": "Public base58 Solana token mint address",
                            }
                        },
                        "required": ["mint"],
                    },
                },
            ),
            handler=handle_check_token,
            input_model=CheckTokenRugShieldInput,
        ),
        Tool(
            spec=ToolSpec(
                name="scan_wallet_unclaimed_rent",
                description=(
                    "Read-only, non-custodial scan for reclaimable SOL rent locked in empty "
                    "SPL and Token-2022 Associated Token Accounts (0% fee on first claim)."
                ),
                input_schema={
                    "name": "scan_wallet_unclaimed_rent",
                    "description": "Preview reclaimable Solana empty ATA rent",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "wallet": {
                                "type": "string",
                                "description": "Public base58 Solana wallet address",
                            }
                        },
                        "required": ["wallet"],
                    },
                },
            ),
            handler=handle_scan_wallet,
            input_model=ScanWalletRentInput,
        ),
    ]
