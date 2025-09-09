import aiohttp
import logging
from typing import Dict, Any, List
import base64

from ..core.tools import Tool, ToolSpec
from ..utils.http_client import get_session
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class JupiterTools:
    def __init__(self, solana_tools=None):
        # Jupiter v6 Quote/Swap API base
        self.base_url = "https://quote-api.jup.ag/v6"
        self.price_url = "https://api.jup.ag/price/v3"
        self.solana_tools = solana_tools

    async def close(self):
        """Close method for compatibility - shared client handles cleanup."""
        pass  # Shared HTTP client handles session lifecycle

    async def get_token_price(self, token_mint: str) -> Dict[str, Any]:
        """Get token price from Jupiter Price API v3."""
        try:
            session = await get_session()

            params = {"ids": token_mint}

            async with session.get(f"{self.price_url}/price", params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter price API error {response.status}: {error_text}")
                    return {"error": f"Price API error {response.status}: {error_text}"}

                data = await response.json()

                if "data" not in data or token_mint not in data["data"]:
                    return {"error": f"No price data found for token {token_mint}"}

                token_data = data["data"][token_mint]

                logger.info(f"Got price for {token_mint}: ${token_data.get('price', 0)}")
                return {
                    "token_mint": token_mint,
                    "price_usd": token_data.get("price", 0),
                    "symbol": token_data.get("symbol", "Unknown"),
                    "name": token_data.get("name", "Unknown"),
                    "decimals": token_data.get("decimals", 0),
                    "source": "jupiter",
                }

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting token price: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting token price: {e}")
            return {"error": str(e)}

    async def get_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict[str, Any]:
        """Get a swap quote from Jupiter."""
        try:
            session = await get_session()

            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": str(slippage_bps),
                "swapMode": "ExactIn",
                "restrictIntermediateTokens": "true",
            }

            # v6 quote endpoint
            async with session.get(f"{self.base_url}/quote", params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter quote API error {response.status}: {error_text}")

                    # Provide more helpful error messages
                    if response.status == 400:
                        return {
                            "error": f"Invalid quote request: {error_text}",
                            "help": "Check that token mint addresses are valid and amount is positive.",
                        }
                    elif response.status == 404:
                        return {
                            "error": "No route found for this token pair",
                            "help": "This token pair may not have sufficient liquidity or trading restrictions.",
                        }
                    else:
                        return {
                            "error": f"Quote API error {response.status}: {error_text}",
                            "help": "This may be a temporary Jupiter API issue. Try again later.",
                        }

                data = await response.json()

                logger.info(
                    f"Got quote: {amount} {input_mint} -> {data.get('outAmount', 0)} {output_mint}"
                )
                return {
                    "quote": data,
                    "input_mint": input_mint,
                    "output_mint": output_mint,
                    "input_amount": amount,
                    "output_amount": data.get("outAmount", 0),
                    "price_impact_pct": data.get("priceImpactPct", 0),
                    "route_plan": data.get("routePlan", []),
                }

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting quote: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting quote: {e}")
            return {"error": str(e)}

    async def create_swap_transaction(
        self, user_public_key: str, quote_response: Dict[str, Any], priority_fee: int = 1000
    ) -> Dict[str, Any]:
        """Create a swap transaction from a quote."""
        try:
            session = await get_session()

            payload = {
                "userPublicKey": user_public_key,
                "quoteResponse": quote_response,
                "dynamicComputeUnitLimit": True,
                "dynamicSlippage": True,
                "prioritizationFeeLamports": {
                    "priorityLevelWithMaxLamports": {
                        "priorityLevel": "medium",
                        "maxLamports": priority_fee,
                    }
                },
            }

            logger.info(f"Creating swap transaction for {user_public_key}")

            # v6 swap endpoint
            async with session.post(f"{self.base_url}/swap", json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter swap API error {response.status}: {error_text}")
                    return {"error": f"Swap API error {response.status}: {error_text}"}

                data = await response.json()

                logger.info("Swap transaction created successfully")

                # Safely extract priority fee with proper error handling
                priority_fee_lamports = 0
                try:
                    priority_fee_instructions = data.get("priorityFeeInstructions", {})
                    if isinstance(priority_fee_instructions, dict):
                        compute_budget_instructions = priority_fee_instructions.get(
                            "computeBudgetInstructions", []
                        )
                        if (
                            isinstance(compute_budget_instructions, list)
                            and compute_budget_instructions
                        ):
                            first_instruction = compute_budget_instructions[0]
                            if isinstance(first_instruction, dict):
                                instruction_data = first_instruction.get("data", {})
                                if isinstance(instruction_data, dict):
                                    micro_lamports = instruction_data.get("microLamports", 0)
                                    if (
                                        isinstance(micro_lamports, (int, float))
                                        and micro_lamports > 0
                                    ):
                                        priority_fee_lamports = int(micro_lamports) // 1000
                except (TypeError, KeyError, ValueError, AttributeError) as e:
                    logger.warning(f"Could not extract priority fee: {e}")
                    priority_fee_lamports = 0

                return {
                    "success": True,
                    "transaction": data.get("swapTransaction"),
                    "last_valid_block_height": data.get("lastValidBlockHeight"),
                    "priority_fee_lamports": priority_fee_lamports,
                }

        except aiohttp.ClientError as e:
            logger.error(f"Network error creating swap: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error creating swap: {e}")
            return {"error": str(e)}

    async def execute_swap(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Dict[str, Any]:
        """Execute a complete swap from quote to transaction."""
        if not self.solana_tools or not self.solana_tools.keypair:
            return {
                "error": "No Solana wallet configured for swaps",
                "help": "Please set up your Solana wallet using the /wallet command or configure a private key in your environment.",
            }

        try:
            # Get quote
            logger.info(f"Getting quote for {amount} tokens from {input_mint} to {output_mint}")
            quote_result = await self.get_quote(input_mint, output_mint, amount, slippage_bps)
            if "error" in quote_result:
                error_msg = quote_result["error"]
                logger.error(f"Quote failed: {error_msg}")
                return {
                    "error": f"Failed to get swap quote: {error_msg}",
                    "help": "This could indicate: 1) Invalid token mint address, 2) Insufficient liquidity, 3) Network issues",
                }

            # Create swap transaction
            user_public_key = str(self.solana_tools.keypair.pubkey())
            logger.info(f"Creating swap transaction for wallet {user_public_key[:8]}...")
            swap_result = await self.create_swap_transaction(user_public_key, quote_result["quote"])

            if "error" in swap_result:
                error_msg = swap_result["error"]
                logger.error(f"Swap transaction creation failed: {error_msg}")
                return {
                    "error": f"Failed to create swap transaction: {error_msg}",
                    "help": "This could indicate: 1) Invalid quote response, 2) Wallet issues, 3) Network connectivity problems",
                }

            if not swap_result.get("transaction"):
                return {
                    "error": "No transaction data received from Jupiter",
                    "help": "Jupiter API did not return transaction data. This may be a temporary service issue.",
                }

            # Deserialize and sign the transaction
            transaction_data = base64.b64decode(swap_result["transaction"])

            # Parse the transaction
            try:
                # Import solders for transaction handling
                from solders.transaction import VersionedTransaction

                # Deserialize the versioned transaction
                versioned_tx = VersionedTransaction.from_bytes(transaction_data)

                # Create a new signed transaction with the keypair
                signed_tx = VersionedTransaction(versioned_tx.message, [self.solana_tools.keypair])

                # Send the transaction to Solana
                from solana.rpc.types import TxOpts

                # Get the properly initialized client
                client = await self.solana_tools._get_client()
                tx_hash = await client.send_transaction(
                    signed_tx, opts=TxOpts(skip_preflight=False, max_retries=3)
                )

                logger.info(f"Swap transaction executed successfully: {tx_hash}")

                return {
                    "success": True,
                    "input_mint": input_mint,
                    "output_mint": output_mint,
                    "input_amount": amount,
                    "expected_output_amount": quote_result.get("output_amount", 0),
                    "price_impact_pct": quote_result.get("price_impact_pct", 0),
                    "transaction_id": str(tx_hash),
                }

            except Exception as sign_error:
                logger.error(f"Failed to execute swap transaction: {sign_error}")
                return {"error": f"Swap failed: {str(sign_error)}"}

        except Exception as e:
            logger.error(f"Swap execution failed: {e}")
            return {"error": str(e)}

    async def get_multiple_token_prices(self, token_mints: List[str]) -> Dict[str, Any]:
        """Get prices for multiple tokens from Jupiter Price API v3."""
        try:
            session = await get_session()

            # Jupiter v3 API supports comma-separated mint addresses
            params = {"ids": ",".join(token_mints)}

            async with session.get(f"{self.price_url}/price", params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter price API error {response.status}: {error_text}")
                    return {"error": f"Price API error {response.status}: {error_text}"}

                data = await response.json()

                if "data" not in data:
                    return {"error": "No price data received"}

                result = {"prices": {}, "missing": []}

                for mint in token_mints:
                    if mint in data["data"]:
                        token_data = data["data"][mint]
                        result["prices"][mint] = {
                            "price_usd": token_data.get("price", 0),
                            "symbol": token_data.get("symbol", "Unknown"),
                            "name": token_data.get("name", "Unknown"),
                            "decimals": token_data.get("decimals", 0),
                        }
                    else:
                        result["missing"].append(mint)

                logger.info(
                    f"Got prices for {len(result['prices'])} tokens, {len(result['missing'])} missing"
                )
                return result

        except aiohttp.ClientError as e:
            logger.error(f"Network error getting token prices: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting token prices: {e}")
            return {"error": str(e)}


def create_jupiter_tools(jupiter_tools: JupiterTools) -> List[Tool]:
    """Create Jupiter tool instances."""

    class SwapQuoteInput(BaseModel):
        input_mint: str = Field(..., description="Input token mint address")
        output_mint: str = Field(..., description="Output token mint address")
        amount: int = Field(..., gt=0, description="Input amount in token's smallest unit")
        slippage_bps: int = Field(50, ge=1, le=1000, description="Slippage in bps")

        @field_validator("input_mint", "output_mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    class JupiterSwapInput(SwapQuoteInput):
        pass

    class TokenPriceInput(BaseModel):
        token_mint: str = Field(..., description="Token mint address to get price for")

        @field_validator("token_mint")
        @classmethod
        def _validate_mint(cls, v: str) -> str:
            if not isinstance(v, str) or len(v) < 32 or len(v) > 44:
                raise ValueError("Invalid token mint address")
            return v

    async def handle_get_swap_quote(args: Dict[str, Any]) -> Dict[str, Any]:
        input_mint = args.get("input_mint", "")
        output_mint = args.get("output_mint", "")
        amount = args.get("amount", 0)
        slippage_bps = args.get("slippage_bps", 50)

        return await jupiter_tools.get_quote(input_mint, output_mint, amount, slippage_bps)

    async def handle_jupiter_swap(args: Dict[str, Any]) -> Dict[str, Any]:
        input_mint = args.get("input_mint", "")
        output_mint = args.get("output_mint", "")
        amount = args.get("amount", 0)
        slippage_bps = args.get("slippage_bps", 50)

        return await jupiter_tools.execute_swap(input_mint, output_mint, amount, slippage_bps)

    async def handle_get_token_price(args: Dict[str, Any]) -> Dict[str, Any]:
        token_mint = args.get("token_mint", "")
        return await jupiter_tools.get_token_price(token_mint)

    tools = [
        Tool(
            spec=ToolSpec(
                name="get_swap_quote",
                description="Get a swap quote from Jupiter for token exchange",
                input_schema={
                    "name": "get_swap_quote",
                    "description": "Get Jupiter swap quote",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_mint": {
                                "type": "string",
                                "description": "Input token mint address",
                            },
                            "output_mint": {
                                "type": "string",
                                "description": "Output token mint address",
                            },
                            "amount": {
                                "type": "integer",
                                "description": "Input amount in token's smallest unit",
                            },
                            "slippage_bps": {
                                "type": "integer",
                                "description": "Slippage tolerance in basis points (default: 50 = 0.5%)",
                                "default": 50,
                                "minimum": 1,
                                "maximum": 1000,
                            },
                        },
                        "required": ["input_mint", "output_mint", "amount"],
                    },
                },
            ),
            handler=handle_get_swap_quote,
            input_model=SwapQuoteInput,
        ),
        Tool(
            spec=ToolSpec(
                name="jupiter_swap",
                description="Execute a token swap using Jupiter aggregator",
                input_schema={
                    "name": "jupiter_swap",
                    "description": "Execute Jupiter token swap",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_mint": {
                                "type": "string",
                                "description": "Input token mint address",
                            },
                            "output_mint": {
                                "type": "string",
                                "description": "Output token mint address",
                            },
                            "amount": {
                                "type": "integer",
                                "description": "Input amount in token's smallest unit",
                            },
                            "slippage_bps": {
                                "type": "integer",
                                "description": "Slippage tolerance in basis points (default: 50 = 0.5%)",
                                "default": 50,
                                "minimum": 1,
                                "maximum": 1000,
                            },
                        },
                        "required": ["input_mint", "output_mint", "amount"],
                    },
                },
            ),
            handler=handle_jupiter_swap,
            input_model=JupiterSwapInput,
        ),
        Tool(
            spec=ToolSpec(
                name="get_token_price",
                description="Get current USD price for any Solana token using Jupiter Price API",
                input_schema={
                    "name": "get_token_price",
                    "description": "Get token price in USD",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "token_mint": {
                                "type": "string",
                                "description": "Token mint address to get price for",
                            },
                        },
                        "required": ["token_mint"],
                    },
                },
            ),
            handler=handle_get_token_price,
            input_model=TokenPriceInput,
        ),
    ]

    return tools
