import aiohttp
import logging
from typing import Dict, Any, List

from ..core.tools import Tool, ToolSpec
from pydantic import BaseModel, Field, field_validator
from ..utils.http_client import get_session
from ..utils.error_messages import handle_error_gracefully
from ..utils.transaction_validator import validate_pump_buy, validate_pump_sell

logger = logging.getLogger(__name__)


class PumpFunTools:
    def __init__(self, solana_tools=None):
        self.base_url = "https://pumpportal.fun/api"
        self.solana_tools = solana_tools  # For transaction signing and sending

    async def close(self):
        """Close method for compatibility - shared client handles cleanup."""
        pass  # Shared HTTP client handles session lifecycle

    async def _sign_and_send_transaction(self, transaction_hex: str, action: str) -> Dict[str, Any]:
        """Sign and send a pump.fun transaction with fresh blockhash."""
        if not self.solana_tools or not self.solana_tools.keypair:
            return {"error": "No wallet configured for signing transactions"}

        try:
            # Import solders for transaction handling
            from solders.transaction import VersionedTransaction

            # Convert hex to bytes and deserialize
            transaction_data = bytes.fromhex(transaction_hex)
            versioned_tx = VersionedTransaction.from_bytes(transaction_data)

            # MessageV0 objects are immutable, so we can't patch the blockhash
            # Instead, just sign the transaction as-is with our keypair
            # The pump.fun API should already provide a valid blockhash

            # Create a new signed transaction with our keypair
            signed_tx = VersionedTransaction(versioned_tx.message, [self.solana_tools.keypair])

            # Send the transaction to Solana with optimized settings
            from solana.rpc.types import TxOpts

            # Try sending with skip preflight first for better success rate on pump.fun
            try:
                result = await self.solana_tools.client.send_transaction(
                    signed_tx, opts=TxOpts(skip_preflight=True, max_retries=2)
                )
            except Exception as first_attempt_error:
                error_msg = str(first_attempt_error)
                if "blockhash" in error_msg.lower():
                    logger.warning(
                        f"Blockhash error, transaction may be stale: {first_attempt_error}"
                    )
                    return {"error": "Transaction expired (stale blockhash). Please try again."}
                else:
                    logger.warning(
                        f"Preflight skip failed, retrying with preflight: {first_attempt_error}"
                    )
                    # If that fails, try with preflight enabled
                    result = await self.solana_tools.client.send_transaction(
                        signed_tx, opts=TxOpts(skip_preflight=False, max_retries=1)
                    )

            if result.value:
                tx_signature = str(result.value)
                logger.info(f"Pump.fun {action} transaction executed successfully: {tx_signature}")

                return {"success": True, "transaction_id": tx_signature, "action": action}
            else:
                logger.error("Transaction failed to send - no signature returned")
                return {"error": "Transaction failed: No signature returned"}

        except Exception as e:
            logger.error(f"Failed to execute pump.fun transaction: {e}")
            return {"error": f"Transaction failed: {str(e)}"}

    async def get_token_trades(self, mint: str, limit: int = 10) -> Dict[str, Any]:
        """Get recent trades for a token."""
        try:
            session = await get_session()

            params = {"mint": mint, "limit": str(limit)}

            async with session.get(f"{self.base_url}/trades", params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Pump.fun API error {response.status}: {error_text}")
                    return {"error": f"API error {response.status}: {error_text}"}

                data = await response.json()

                logger.info(f"Retrieved {len(data.get('trades', []))} trades for {mint}")
                return {
                    "mint": mint,
                    "trades": data.get("trades", []),
                    "total_trades": len(data.get("trades", [])),
                }

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting trades: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting trades: {e}")
            return {"error": str(e)}

    async def create_buy_transaction(
        self, public_key: str, mint: str, amount: float, slippage: int = 1
    ) -> Dict[str, Any]:
        """Create a buy transaction for a token on pump.fun."""
        try:
            session = await get_session()

            payload = {
                "publicKey": public_key,
                "action": "buy",
                "mint": mint,
                "denominatedInSol": True,
                "amount": amount,
                "slippage": slippage,
                "priorityFee": 0.00001,
            }

            logger.info(f"Creating buy transaction: {amount} SOL for {mint}")

            async with session.post(f"{self.base_url}/trade-local", json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Buy transaction creation failed {response.status}: {error_text}")
                    return {"error": f"Transaction creation failed: {error_text}"}

                # Response is raw transaction data
                transaction_data = await response.read()
                transaction_hex = transaction_data.hex()

                logger.info(f"Buy transaction created successfully for {mint}")

                # Sign and send the transaction automatically
                sign_result = await self._sign_and_send_transaction(transaction_hex, "buy")

                # Add transaction details to the result
                if "success" in sign_result:
                    sign_result.update({"mint": mint, "amount_sol": amount, "slippage": slippage})

                return sign_result

        except aiohttp.ClientError as e:
            logger.error(f"Network error creating buy transaction: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error creating buy transaction: {e}")
            return handle_error_gracefully(e, {"operation": "pump_fun_buy"})

    async def create_sell_transaction(
        self, public_key: str, mint: str, percentage: int = 100, slippage: int = 1
    ) -> Dict[str, Any]:
        """Create a sell transaction for a token on pump.fun."""
        try:
            session = await get_session()

            payload = {
                "publicKey": public_key,
                "action": "sell",
                "mint": mint,
                "denominatedInSol": False,
                "amount": percentage,  # Percentage of holdings to sell
                "slippage": slippage,
                "priorityFee": 0.00001,
            }

            logger.info(f"Creating sell transaction: {percentage}% of {mint}")

            async with session.post(f"{self.base_url}/trade-local", json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        f"Sell transaction creation failed {response.status}: {error_text}"
                    )
                    return {"error": f"Transaction creation failed: {error_text}"}

                # Response is raw transaction data
                transaction_data = await response.read()
                transaction_hex = transaction_data.hex()

                logger.info(f"Sell transaction created successfully for {mint}")

                # Sign and send the transaction automatically
                sign_result = await self._sign_and_send_transaction(transaction_hex, "sell")

                # Add transaction details to the result
                if "success" in sign_result:
                    sign_result.update(
                        {"mint": mint, "percentage": percentage, "slippage": slippage}
                    )

                return sign_result

        except aiohttp.ClientError as e:
            logger.error(f"Network error creating sell transaction: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error creating sell transaction: {e}")
            return {"error": str(e)}

    async def get_token_info(self, mint: str) -> Dict[str, Any]:
        """Get basic information about a token.

        Note: The pumpportal.fun API doesn't expose coin-data; use the
        pump.fun frontend API for token metadata.
        """
        try:
            session = await get_session()

            # Primary: pump.fun frontend API for coin metadata
            url = f"https://frontend-api.pump.fun/coins/{mint}"
            async with session.get(url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(
                        f"Pump.fun frontend API error {response.status}: {error_text} — attempting DexScreener fallback"
                    )
                    # Fallback to DexScreener if pump.fun frontend API is unavailable
                    ds_url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
                    async with session.get(ds_url) as ds_resp:
                        if ds_resp.status != 200:
                            ds_text = await ds_resp.text()
                            logger.error(f"DexScreener fallback error {ds_resp.status}: {ds_text}")
                            return {"error": f"API error {response.status}: {error_text}"}

                        ds_data = await ds_resp.json()
                        pairs = ds_data.get("pairs") or []
                        # Pick the highest liquidity pair as representative
                        best = None
                        best_liq = -1.0
                        for p in pairs:
                            try:
                                liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
                                if liq > best_liq:
                                    best = p
                                    best_liq = liq
                            except Exception:
                                continue
                        if not best:
                            return {"error": "No token data available from pump.fun or DexScreener"}

                        base = best.get("baseToken") or {}
                        info = {
                            "mint": mint,
                            "name": base.get("name") or "Unknown",
                            "symbol": base.get("symbol") or "Unknown",
                            "description": "",
                            "market_cap": best.get("fdv") or 0,
                            "price": best.get("priceUsd") or 0,
                            "bonding_curve": {},
                            "twitter": None,
                            "telegram": None,
                            "website": None,
                            "raw": ds_data,
                            "source": "dexscreener",
                        }
                        logger.info(f"Retrieved token info from DexScreener for {mint}")
                        return info

                data = await response.json()

                # Map common fields safely
                name = data.get("name") or data.get("coin_name") or "Unknown"
                symbol = data.get("symbol") or data.get("ticker") or "Unknown"
                description = data.get("description") or data.get("bio") or ""
                price = (
                    data.get("price")
                    or data.get("usdMarketCap")  # some endpoints expose market cap instead
                    or 0
                )
                bonding_curve = data.get("bonding_curve") or data.get("bondingCurve") or {}

                links = data.get("links") or {}
                twitter = data.get("twitter") or links.get("twitter")
                telegram = data.get("telegram") or links.get("telegram")
                website = data.get("website") or links.get("website")

                logger.info(f"Retrieved token info for {mint}")
                return {
                    "mint": mint,
                    "name": name,
                    "symbol": symbol,
                    "description": description,
                    "market_cap": data.get("market_cap") or data.get("marketCap") or 0,
                    "price": price,
                    "bonding_curve": bonding_curve,
                    "twitter": twitter,
                    "telegram": telegram,
                    "website": website,
                    "raw": data,
                    "source": "pump.fun",
                }

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting token info: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting token info: {e}")
            return {"error": str(e)}


def create_pump_fun_tools(pump_fun_tools: PumpFunTools, agent=None) -> List[Tool]:
    """Create Pump.fun tool instances."""

    class PumpBuyInput(BaseModel):
        mint: str = Field(..., description="Token mint address")
        amount: float = Field(..., gt=0, le=1000, description="Amount of SOL to spend")
        slippage: int = Field(5, ge=1, le=50, description="Slippage tolerance (1-50%)")

        @field_validator("mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    class PumpSellInput(BaseModel):
        mint: str = Field(..., description="Token mint address")
        percentage: int = Field(100, ge=1, le=100, description="Percentage to sell (1-100)")
        slippage: int = Field(5, ge=1, le=50, description="Slippage tolerance (1-50%)")

        @field_validator("mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    class TokenTradesInput(BaseModel):
        mint: str = Field(..., description="Token mint address")
        limit: int = Field(10, ge=1, le=50, description="Number of trades to retrieve")

        @field_validator("mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    class PumpTokenInfoInput(BaseModel):
        mint: str = Field(..., description="Token mint address")

        @field_validator("mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    async def handle_pump_fun_buy(args: Dict[str, Any]) -> Dict[str, Any]:
        # Use configured wallet automatically
        public_key = (
            pump_fun_tools.solana_tools.wallet_address if pump_fun_tools.solana_tools else None
        )
        if not public_key:
            return handle_error_gracefully(
                ValueError("No wallet configured for trading"), {"operation": "pump_fun_buy"}
            )

        # Get current balance for validation
        try:
            wallet_balance = 0.0
            if pump_fun_tools.solana_tools:
                balance_result = await pump_fun_tools.solana_tools.get_balance()
                if "sol_balance" in balance_result:
                    wallet_balance = balance_result["sol_balance"]
        except Exception as e:
            logger.warning(f"Could not get balance for validation: {e}")

        # Pre-transaction validation
        validation_result = await validate_pump_buy(
            wallet_balance,
            args["amount"],
            args.get("slippage", 5),
            args["mint"],
        )

        # If validation fails, return error
        if not validation_result.is_valid:
            from ..utils.transaction_validator import TransactionValidator

            validator = TransactionValidator()
            error_message = validator.format_validation_result(validation_result)
            return {
                "error": True,
                "category": "validation",
                "title": "Transaction Validation Failed",
                "message": "Cannot proceed with pump.fun buy",
                "validation_details": error_message,
                "solutions": validation_result.suggestions[:3],  # Top 3 suggestions
            }

        # Show warnings if any (but proceed)
        if validation_result.warnings:
            logger.warning(f"Transaction warnings: {validation_result.warnings}")

        result = await pump_fun_tools.create_buy_transaction(
            public_key,
            args["mint"],
            args["amount"],
            args.get("slippage", 5),  # Default to 5% for pump.fun
        )

        # Invalidate balance cache after successful transaction
        if agent and "success" in result:
            agent.invalidate_balance_cache()

        return result

    async def handle_pump_fun_sell(args: Dict[str, Any]) -> Dict[str, Any]:
        # Use configured wallet automatically
        public_key = (
            pump_fun_tools.solana_tools.wallet_address if pump_fun_tools.solana_tools else None
        )
        if not public_key:
            return handle_error_gracefully(
                ValueError("No wallet configured for trading"), {"operation": "pump_fun_sell"}
            )

        # Pre-transaction validation
        validation_result = await validate_pump_sell(
            args.get("percentage", 100),
            args.get("slippage", 5),
            args["mint"],
        )

        # If validation fails, return error
        if not validation_result.is_valid:
            from ..utils.transaction_validator import TransactionValidator

            validator = TransactionValidator()
            error_message = validator.format_validation_result(validation_result)
            return {
                "error": True,
                "category": "validation",
                "title": "Transaction Validation Failed",
                "message": "Cannot proceed with pump.fun sell",
                "validation_details": error_message,
                "solutions": validation_result.suggestions[:3],
            }

        # Show warnings if any (but proceed)
        if validation_result.warnings:
            logger.warning(f"Transaction warnings: {validation_result.warnings}")

        result = await pump_fun_tools.create_sell_transaction(
            public_key,
            args["mint"],
            args.get("percentage", 100),
            args.get("slippage", 5),  # Default to 5% for pump.fun
        )

        # Invalidate balance cache after successful transaction
        if agent and "success" in result:
            agent.invalidate_balance_cache()

        return result

    async def handle_get_token_trades(args: Dict[str, Any]) -> Dict[str, Any]:
        mint = args.get("mint", "")
        limit = args.get("limit", 10)
        return await pump_fun_tools.get_token_trades(mint, limit)

    async def handle_get_pump_token_info(args: Dict[str, Any]) -> Dict[str, Any]:
        mint = args.get("mint", "")
        return await pump_fun_tools.get_token_info(mint)

    tools = [
        Tool(
            spec=ToolSpec(
                name="pump_fun_buy",
                description="Buy a token on pump.fun using the configured wallet. Executes immediately with automatic wallet and slippage settings.",
                input_schema={
                    "name": "pump_fun_buy",
                    "description": "Buy token on pump.fun",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {"type": "string", "description": "Token mint address"},
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to spend",
                                "minimum": 0.001,
                                "maximum": 1000,
                            },
                            "slippage": {
                                "type": "integer",
                                "description": "Slippage tolerance (1-50%)",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 5,
                            },
                        },
                        "required": ["mint", "amount"],
                    },
                },
            ),
            handler=handle_pump_fun_buy,
            input_model=PumpBuyInput,
        ),
        Tool(
            spec=ToolSpec(
                name="pump_fun_sell",
                description="Sell a token on pump.fun using the configured wallet. Executes immediately with automatic wallet and slippage settings.",
                input_schema={
                    "name": "pump_fun_sell",
                    "description": "Sell token on pump.fun",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {"type": "string", "description": "Token mint address"},
                            "percentage": {
                                "type": "integer",
                                "description": "Percentage of holdings to sell (1-100%)",
                                "minimum": 1,
                                "maximum": 100,
                                "default": 100,
                            },
                            "slippage": {
                                "type": "integer",
                                "description": "Slippage tolerance (1-50%)",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 5,
                            },
                        },
                        "required": ["mint"],
                    },
                },
            ),
            handler=handle_pump_fun_sell,
            input_model=PumpSellInput,
        ),
        Tool(
            spec=ToolSpec(
                name="get_token_trades",
                description="Get recent trading activity for a pump.fun token",
                input_schema={
                    "name": "get_token_trades",
                    "description": "Get token trading activity",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {"type": "string", "description": "Token mint address"},
                            "limit": {
                                "type": "integer",
                                "description": "Number of trades to retrieve (1-50)",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 10,
                            },
                        },
                        "required": ["mint"],
                    },
                },
            ),
            handler=handle_get_token_trades,
            input_model=TokenTradesInput,
        ),
        Tool(
            spec=ToolSpec(
                name="get_pump_token_info",
                description="Get detailed information about a pump.fun token",
                input_schema={
                    "name": "get_pump_token_info",
                    "description": "Get pump.fun token information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mint": {"type": "string", "description": "Token mint address"}
                        },
                        "required": ["mint"],
                    },
                },
            ),
            handler=handle_get_pump_token_info,
            input_model=PumpTokenInfoInput,
        ),
    ]

    return tools
