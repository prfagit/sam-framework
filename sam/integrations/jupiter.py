import aiohttp
import logging
from typing import Dict, Any, List
import base64

from ..core.tools import Tool, ToolSpec
from ..utils.decorators import rate_limit, retry_with_backoff, log_execution
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)


class JupiterTools:
    def __init__(self, solana_tools=None):
        self.base_url = "https://quote-api.jup.ag"
        self.solana_tools = solana_tools

    async def close(self):
        """Close method for compatibility - shared client handles cleanup."""
        pass  # Shared HTTP client handles session lifecycle

    @rate_limit("jupiter")
    @retry_with_backoff(max_retries=3)
    @log_execution()
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
            }

            async with session.get(f"{self.base_url}/v6/quote", params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Jupiter quote API error {response.status}: {error_text}")
                    return {"error": f"Quote API error {response.status}: {error_text}"}

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
                "config": {
                    "priorityLevelWithMaxLamports": {
                        "priorityLevel": "medium",
                        "maxLamports": priority_fee,
                    },
                    "dynamicComputeUnitLimit": True,
                    "dynamicSlippage": {"maxBps": 300},
                },
            }

            logger.info(f"Creating swap transaction for {user_public_key}")

            async with session.post(f"{self.base_url}/v6/swap", json=payload) as response:
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
            return {"error": "No Solana wallet configured for swaps"}

        try:
            # Get quote
            quote_result = await self.get_quote(input_mint, output_mint, amount, slippage_bps)
            if "error" in quote_result:
                return quote_result

            # Create swap transaction
            user_public_key = str(self.solana_tools.keypair.pubkey())
            swap_result = await self.create_swap_transaction(user_public_key, quote_result["quote"])

            if "error" in swap_result:
                return swap_result

            if not swap_result.get("transaction"):
                return {"error": "No transaction data received from Jupiter"}

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

                tx_hash = await self.solana_tools.client.send_transaction(
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


def create_jupiter_tools(jupiter_tools: JupiterTools) -> List[Tool]:
    """Create Jupiter tool instances."""

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
        ),
    ]

    return tools
