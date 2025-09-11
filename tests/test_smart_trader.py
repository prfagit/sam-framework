import pytest
import asyncio

from sam.integrations.smart_trader import SmartTrader, WSOL_MINT


class FakeSolana:
    def __init__(self, wallet, balances):
        self.wallet_address = wallet
        self._balances = balances  # dict mint -> amount (smallest unit)

    async def get_token_accounts(self, _addr=None):
        return {
            "token_accounts": [
                {"mint": m, "amount": a, "decimals": 9, "uiAmount": a / 1_000_000_000}
                for m, a in self._balances.items()
            ]
        }


class FakePump:
    def __init__(self, succeed=False):
        self.succeed = succeed
        self.called = False

    async def create_sell_transaction(self, public_key, mint, percentage, slippage):
        self.called = True
        if self.succeed:
            return {"success": True, "transaction_id": "pump_tx"}
        return {"error": "pump fail"}


class FakeJupiter:
    def __init__(self):
        self.calls = []

    async def execute_swap(self, input_mint, output_mint, amount, slippage_bps):
        self.calls.append((input_mint, output_mint, amount, slippage_bps))
        return {"success": True, "transaction_id": "jup_tx"}


@pytest.mark.asyncio
async def test_smart_sell_fallback_to_jupiter():
    mint = "FakeMint1111111111111111111111111111111111111"
    balances = {mint: 2_000_000_000}  # 2 tokens (decimals=9)
    sol = FakeSolana("Wallet111", balances)
    pump = FakePump(succeed=False)
    jup = FakeJupiter()

    trader = SmartTrader(pump_tools=pump, jupiter_tools=jup, solana_tools=sol)

    res = await trader.smart_sell(mint, percentage=50, slippage_percent=5)
    assert res.get("success") is True
    # Jupiter should be called with 1 token (50% of 2), smallest units
    assert jup.calls, "Jupiter was not called"
    call = jup.calls[0]
    assert call[0] == mint and call[1] == WSOL_MINT
    assert call[2] == 1_000_000_000  # half


@pytest.mark.asyncio
async def test_smart_sell_uses_pump_when_available():
    mint = "FakeMint2222222222222222222222222222222222222"
    balances = {mint: 5_000_000_000}
    sol = FakeSolana("Wallet222", balances)
    pump = FakePump(succeed=True)
    jup = FakeJupiter()

    trader = SmartTrader(pump_tools=pump, jupiter_tools=jup, solana_tools=sol)

    res = await trader.smart_sell(mint, percentage=10, slippage_percent=5)
    assert res.get("success") is True
    assert pump.called is True
    # Ensure no Jupiter call when pump succeeds
    assert not jup.calls

