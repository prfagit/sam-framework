"""Unit tests for Solana Rent & Rug Shield integration."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from sam.integrations.rentshield import (
    RentShieldTools,
    create_rentshield_tools,
    is_valid_solana_pubkey,
)

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SAMPLE_WALLET = "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"
FAKE_SECRET_KEY = (
    "5MaiiCavjCmn9Hs1o3eznqDEhRwxo7pXiAYez7keQUviUkauRiTMD8DrESdrNjN8zd9mTmVhRvBJeg5vhyvgrAhG"
)


class _MockResponse:
    def __init__(self, status: int, payload: Dict[str, Any]) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "_MockResponse":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def json(self) -> Dict[str, Any]:
        return self._payload


class _MockSession:
    def __init__(self, steps: List[_MockResponse], recorded: List[Tuple[str, str, Any]]) -> None:
        self._steps = steps
        self._recorded = recorded

    async def __aenter__(self) -> "_MockSession":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def request(
        self,
        method: str,
        url: str,
        headers: Any = None,
        json: Any = None,
    ) -> _MockResponse:
        self._recorded.append((method, url, json))
        return self._steps.pop(0)

    def get(self, url: str, headers: Any = None) -> _MockResponse:
        self._recorded.append(("GET", url, None))
        return self._steps.pop(0)


class TestRentShieldIntegration(unittest.IsolatedAsyncioTestCase):
    def test_pubkey_validation_blocks_secret_keys_and_mnemonics(self) -> None:
        self.assertTrue(is_valid_solana_pubkey(USDC_MINT))
        self.assertTrue(is_valid_solana_pubkey(SAMPLE_WALLET))
        self.assertFalse(is_valid_solana_pubkey(FAKE_SECRET_KEY))
        self.assertFalse(is_valid_solana_pubkey("word1 word2 word3 word4"))
        self.assertFalse(is_valid_solana_pubkey(""))

    async def test_rejects_private_key_without_network_call(self) -> None:
        client = RentShieldTools()
        with patch("sam.integrations.rentshield.aiohttp.ClientSession") as session_cls:
            with self.assertRaises(ValueError):
                await client.check_token_rug_shield(FAKE_SECRET_KEY)
            with self.assertRaises(ValueError):
                await client.scan_wallet_unclaimed_rent(FAKE_SECRET_KEY)
            session_cls.assert_not_called()

    async def test_check_token_rug_shield_with_live_endpoint_fallback(self) -> None:
        client = RentShieldTools(api_url="https://rentandrugshield.com")
        recorded: List[Tuple[str, str, Any]] = []
        steps = [
            _MockResponse(404, {}),
            _MockResponse(200, {"ok": True, "api_base": "https://edge.rentandrugshield.example"}),
            _MockResponse(
                200,
                {
                    "ok": True,
                    "mint": USDC_MINT,
                    "symbol": "USDC",
                    "name": "USD Coin",
                    "token_program": "SPL Token",
                    "score": 100,
                    "safe_to_buy": True,
                    "verdict": "SAFE",
                    "layers_checked": 11,
                    "layers_passed": 11,
                    "checklist_summary": "11/11",
                    "checks": [{"layer": 1, "key": "mint_auth", "passed": True}],
                },
            ),
        ]
        with patch(
            "sam.integrations.rentshield.aiohttp.ClientSession",
            return_value=_MockSession(steps, recorded),
        ):
            res = await client.check_token_rug_shield(USDC_MINT)

        self.assertEqual(res["mint"], USDC_MINT)
        self.assertEqual(res["score"], 100)
        self.assertTrue(res["safe_to_buy"])
        self.assertEqual(res["layers_checked"], 11)
        self.assertEqual(len(recorded), 3)

    async def test_scan_wallet_unclaimed_rent_and_tool_wrappers(self) -> None:
        client = RentShieldTools(api_url="https://edge.rentandrugshield.example")
        recorded: List[Tuple[str, str, Any]] = []
        steps = [
            _MockResponse(
                200,
                {
                    "ok": True,
                    "wallet": SAMPLE_WALLET,
                    "is_first_free_claim": True,
                    "effective_fee_bps": 0,
                    "reclaimable_count": 5,
                    "empty_count": 5,
                    "total_reclaimable_sol": 0.010196,
                    "total_reclaimable_lamports": 10196400,
                },
            )
        ]
        tools = create_rentshield_tools(client)
        self.assertEqual(
            [t.spec.name for t in tools], ["check_token_rug_shield", "scan_wallet_unclaimed_rent"]
        )

        with patch(
            "sam.integrations.rentshield.aiohttp.ClientSession",
            return_value=_MockSession(steps, recorded),
        ):
            res = await tools[1].handler({"wallet": SAMPLE_WALLET})

        self.assertTrue(res["is_first_free_claim"])
        self.assertEqual(res["effective_fee_bps"], 0)
        self.assertEqual(res["empty_count"], 5)
        self.assertEqual(recorded[0][2], {"wallet": SAMPLE_WALLET, "user_initiated": False})


if __name__ == "__main__":
    unittest.main()
