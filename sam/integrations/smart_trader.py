import logging
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field, field_validator

from ..core.tools import Tool, ToolSpec

logger = logging.getLogger(__name__)


WSOL_MINT = "So11111111111111111111111111111111111111112"


class PumpTools(Protocol):
    async def create_buy_transaction(
        self, wallet: str, mint: str, amount_sol: float, slippage_percent: int
    ) -> Dict[str, Any]:
        ...

    async def create_sell_transaction(
        self, wallet: str, mint: str, percentage: int, slippage_percent: int
    ) -> Dict[str, Any]:
        ...


class JupiterTools(Protocol):
    async def execute_swap(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int
    ) -> Dict[str, Any]:
        ...


class SolanaTools(Protocol):
    wallet_address: Optional[str]
    keypair: Any

    async def get_token_accounts(self, wallet: str) -> Dict[str, Any]:
        ...

    async def _get_client(self) -> Any:
        ...


class SmartTrader:
    def __init__(
        self,
        pump_tools: Optional[PumpTools] = None,
        jupiter_tools: Optional[JupiterTools] = None,
        solana_tools: Optional[SolanaTools] = None,
    ) -> None:
        self.pump: Optional[PumpTools] = pump_tools
        self.jupiter: Optional[JupiterTools] = jupiter_tools
        self.solana: Optional[SolanaTools] = solana_tools

    async def smart_buy(
        self, mint: str, amount_sol: float, slippage_percent: int = 5
    ) -> Dict[str, Any]:
        """Try pump.fun first; on failure fall back to Jupiter SOL->mint swap."""
        if not self.solana or not getattr(self.solana, "wallet_address", None):
            return {"error": "No wallet configured for trading"}

        wallet_address = self.solana.wallet_address
        if wallet_address is None:
            return {"error": "No wallet configured for trading"}

        wallet = wallet_address

        # 1) Try pump.fun
        if self.pump is not None:
            try:
                logger.info("smart_buy: attempting pump.fun buy")
                res = await self.pump.create_buy_transaction(
                    wallet, mint, amount_sol, slippage_percent
                )
                if isinstance(res, dict) and "error" not in res:
                    res.setdefault("provider", "pump.fun")
                    return res
                else:
                    logger.warning(f"pump.fun buy failed, will fallback: {res}")
            except Exception as e:
                logger.warning(f"pump.fun buy raised, falling back: {e}")

        # 2) Fallback to Jupiter
        if self.jupiter is None:
            return {"error": "Jupiter swap unavailable for fallback"}

        try:
            slippage_bps = max(1, min(1000, int(slippage_percent * 100)))
            amount_lamports = int(amount_sol * 1_000_000_000)
            logger.info(
                f"smart_buy: attempting Jupiter swap SOL->{mint} amount={amount_lamports} bps={slippage_bps}"
            )
            res = await self.jupiter.execute_swap(WSOL_MINT, mint, amount_lamports, slippage_bps)
            if isinstance(res, dict) and "error" not in res:
                res.setdefault("provider", "jupiter")
            return res
        except Exception as e:
            logger.error(f"Jupiter fallback failed: {e}")
            return {"error": f"Jupiter swap failed: {str(e)}"}

    async def smart_sell(
        self, mint: str, percentage: int = 100, slippage_percent: int = 5
    ) -> Dict[str, Any]:
        """Try pump.fun sell first; on failure fall back to Jupiter token->SOL swap.

        percentage: 1..100 of current holdings to sell.
        """
        if not self.solana or not getattr(self.solana, "wallet_address", None):
            return {"error": "No wallet configured for trading"}

        wallet_address = self.solana.wallet_address
        if wallet_address is None:
            return {"error": "No wallet configured for trading"}

        wallet = wallet_address

        # Determine token balance (in smallest units) to sell via Jupiter fallback
        sell_amount_smallest = 0
        try:
            accs = await self.solana.get_token_accounts(wallet)
            for acc in accs.get("token_accounts", []) or []:
                if acc.get("mint") == mint:
                    amt = int(acc.get("amount", 0) or 0)
                    sell_amount_smallest = max(0, int(amt * (percentage / 100.0)))
                    break
        except Exception:
            # Best-effort; if we can't compute, Jupiter fallback may fail and return a helpful error
            sell_amount_smallest = 0

        # 1) Try pump.fun
        if self.pump is not None:
            try:
                logger.info("smart_sell: attempting pump.fun sell")
                res = await self.pump.create_sell_transaction(
                    wallet, mint, percentage, slippage_percent
                )
                if isinstance(res, dict) and "error" not in res:
                    res.setdefault("provider", "pump.fun")
                    return res
                else:
                    logger.warning(f"pump.fun sell failed, will fallback: {res}")
            except Exception as e:
                logger.warning(f"pump.fun sell raised, falling back: {e}")

        # 2) Fallback to Jupiter token->SOL
        if self.jupiter is None:
            return {"error": "Jupiter swap unavailable for fallback"}

        try:
            slippage_bps = max(1, min(1000, int(slippage_percent * 100)))
            if sell_amount_smallest <= 0:
                return {
                    "error": "No balance available to sell for the specified token",
                    "help": "Holdings may be zero or could not be determined.",
                }
            logger.info(
                f"smart_sell: attempting Jupiter swap {mint}->SOL amount={sell_amount_smallest} bps={slippage_bps}"
            )
            res = await self.jupiter.execute_swap(mint, WSOL_MINT, sell_amount_smallest, slippage_bps)
            if isinstance(res, dict) and "error" not in res:
                res.setdefault("provider", "jupiter")
            return res
        except Exception as e:
            logger.error(f"Jupiter fallback sell failed: {e}")
            return {"error": f"Jupiter swap failed: {str(e)}"}


def create_smart_trader_tools(
    trader: SmartTrader,
) -> List[Tool]:
    """Register smart trading helpers."""

    class SmartBuyInput(BaseModel):
        mint: str = Field(..., description="Token mint to buy")
        amount_sol: float = Field(..., gt=0, le=1000, description="Amount of SOL to spend")
        slippage_percent: int = Field(
            5,
            ge=1,
            le=50,
            description="Slippage percent (used for both providers; Jupiter uses equivalent bps)",
        )

        @field_validator("mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    async def handle_smart_buy(args: Dict[str, Any]) -> Dict[str, Any]:
        mint = args.get("mint", "")
        amount_sol = float(args.get("amount_sol", 0))
        slippage_percent = int(args.get("slippage_percent", 5))
        return await trader.smart_buy(mint, amount_sol, slippage_percent)

    class SmartSellInput(BaseModel):
        mint: str = Field(..., description="Token mint to sell")
        percentage: int = Field(100, ge=1, le=100, description="Percentage of holdings to sell (1-100)")
        slippage_percent: int = Field(5, ge=1, le=50, description="Slippage percent for provider")

        @field_validator("mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    async def handle_smart_sell(args: Dict[str, Any]) -> Dict[str, Any]:
        mint = args.get("mint", "")
        percentage = int(args.get("percentage", 100))
        slippage_percent = int(args.get("slippage_percent", 5))
        return await trader.smart_sell(mint, percentage, slippage_percent)

    return [
        Tool(
            spec=ToolSpec(
                name="smart_buy",
                description="Buy a token using best available route: tries pump.fun first, falls back to Jupiter SOL->token.",
                input_schema={
                    "name": "smart_buy",
                    "description": "Smart buy with fallback",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {"type": "string", "description": "Token mint address"},
                            "amount_sol": {
                                "type": "number",
                                "description": "Amount of SOL to spend",
                                "minimum": 0.001,
                                "maximum": 1000,
                            },
                            "slippage_percent": {
                                "type": "integer",
                                "description": "Slippage percent (1-50) applied to provider",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 50,
                            },
                        },
                        "required": ["mint", "amount_sol"],
                    },
                },
            ),
            handler=handle_smart_buy,
            input_model=SmartBuyInput,
        ),
        Tool(
            spec=ToolSpec(
                name="smart_sell",
                description="Sell a token using best route: tries pump.fun first, falls back to Jupiter token->SOL.",
                input_schema={
                    "name": "smart_sell",
                    "description": "Smart sell with fallback",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {"type": "string", "description": "Token mint address"},
                            "percentage": {
                                "type": "integer",
                                "description": "Percentage of holdings to sell (1-100)",
                                "default": 100,
                                "minimum": 1,
                                "maximum": 100,
                            },
                            "slippage_percent": {
                                "type": "integer",
                                "description": "Slippage percent (1-50) applied to provider",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 50,
                            },
                        },
                        "required": ["mint"],
                    },
                },
            ),
            handler=handle_smart_sell,
            input_model=SmartSellInput,
        ),
    ]
