from typing import Dict, Any, Optional
import logging
import base58

from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams

from ...core.tools import Tool, ToolSpec
from ...utils.validators import validate_tool_input
from ...utils.decorators import rate_limit, retry_with_backoff, log_execution
from ...utils.http_client import get_session
from ...utils.error_messages import handle_error_gracefully
from ...utils.price_service import get_price_service

logger = logging.getLogger(__name__)


class SolanaTools:
    def __init__(self, rpc_url: str, private_key: Optional[str] = None):
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url)
        self.keypair = None
        self.wallet_address = None

        if private_key:
            try:
                # Derive keypair from private key
                private_key_bytes = base58.b58decode(private_key)
                self.keypair = Keypair.from_bytes(private_key_bytes)
                self.wallet_address = str(self.keypair.pubkey())
                logger.info(f"Initialized Solana tools with wallet: {self.wallet_address}")
            except (ValueError, TypeError, Exception) as e:
                logger.error(f"Failed to initialize keypair from private key: {e}")
                raise ValueError(f"Invalid private key: {e}")
        else:
            logger.info("Initialized Solana tools without wallet")

    async def close(self):
        """Close the Solana client connection."""
        if self.client:
            await self.client.close()
            logger.info("Closed Solana client connection")

    @rate_limit("solana_rpc")
    @retry_with_backoff(max_retries=2)
    @log_execution()
    async def get_balance(self, address: Optional[str] = None) -> Dict[str, Any]:
        """Get SOL balance and all SPL token balances for an address or the configured wallet."""
        try:
            target_address = address or self.wallet_address
            if not target_address:
                return {"error": "No address provided and no wallet configured"}

            # Convert address string to Pubkey
            pubkey = Pubkey.from_string(target_address)

            # Get SOL balance
            response = await self.client.get_balance(pubkey)

            if response.value is None:
                logger.error(f"Failed to get SOL balance for {target_address}")
                return {"error": "Failed to retrieve SOL balance from RPC"}

            balance_lamports = response.value
            balance_sol = balance_lamports / 1e9  # Convert lamports to SOL

            # Get SPL token balances using getTokenAccountsByOwner
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    target_address,
                    {
                        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"  # SPL Token program
                    },
                    {"encoding": "jsonParsed"},
                ],
            }

            session = await get_session()
            tokens = []

            async with session.post(
                self.rpc_url, json=payload, headers={"Content-Type": "application/json"}
            ) as token_response:
                if token_response.status == 200:
                    token_data = await token_response.json()
                    token_accounts = token_data.get("result", {}).get("value", [])

                    # Parse token balances
                    for account in token_accounts:
                        info = account["account"]["data"]["parsed"]["info"]
                        if (
                            float(info["tokenAmount"]["uiAmount"] or 0) > 0
                        ):  # Only include tokens with balance
                            tokens.append(
                                {
                                    "mint": info["mint"],
                                    "amount": int(info["tokenAmount"]["amount"]),
                                    "uiAmount": float(info["tokenAmount"]["uiAmount"] or 0),
                                    "decimals": info["tokenAmount"]["decimals"],
                                }
                            )

            # Add USD pricing information
            try:
                price_service = await get_price_service()
                portfolio_info = await price_service.format_portfolio_value(balance_sol, tokens)

                result = {
                    "address": target_address,
                    "sol_balance": balance_sol,
                    "sol_balance_lamports": balance_lamports,
                    "sol_usd": portfolio_info.get("sol_usd", 0.0),
                    "sol_price": portfolio_info.get("sol_price", 0.0),
                    "formatted_sol": portfolio_info.get("formatted_sol", f"{balance_sol:.4f} SOL"),
                    "tokens": tokens,
                    "token_count": len(tokens),
                    "total_portfolio_usd": portfolio_info.get("total_usd", 0.0),
                }

                logger.info(
                    f"Retrieved balances for {target_address}: {portfolio_info.get('formatted_sol', f'{balance_sol} SOL')} + {len(tokens)} tokens"
                )
                return result

            except Exception as price_error:
                logger.warning(f"Could not fetch USD prices: {price_error}")
                # Return without USD info if price service fails
                logger.info(
                    f"Retrieved balances for {target_address}: {balance_sol} SOL + {len(tokens)} tokens"
                )
                return {
                    "address": target_address,
                    "sol_balance": balance_sol,
                    "sol_balance_lamports": balance_lamports,
                    "tokens": tokens,
                    "token_count": len(tokens),
                }

        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return handle_error_gracefully(
                e, {"operation": "get_balance", "address": target_address}
            )

    @rate_limit("transfer_sol", identifier_key="to_address")
    @retry_with_backoff(max_retries=1)  # Be careful with transaction retries
    @log_execution()
    async def transfer_sol(self, to_address: str, amount: float) -> Dict[str, Any]:
        """Transfer SOL to another address."""
        if not self.keypair or not self.wallet_address:
            return {"error": "No wallet configured for transfers"}

        try:
            # Convert amount to lamports
            amount_lamports = int(amount * 1e9)

            # Create recipient public key
            recipient_pubkey = Pubkey.from_string(to_address)

            # Create transfer instruction
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.keypair.pubkey(),
                    to_pubkey=recipient_pubkey,
                    lamports=amount_lamports,
                )
            )

            # Get recent blockhash
            recent_blockhash = await self.client.get_latest_blockhash()
            if not recent_blockhash.value:
                return {"error": "Failed to get recent blockhash"}

            # Create and sign transaction
            from solders.transaction import VersionedTransaction
            from solders.message import MessageV0

            # Create a simple versioned transaction
            message = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=[transfer_instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash.value.blockhash,
            )

            # Create versioned transaction and sign
            versioned_tx = VersionedTransaction(message, [self.keypair])

            # Send transaction
            result = await self.client.send_transaction(versioned_tx, TxOpts(skip_preflight=False))

            if result.value:
                tx_signature = str(result.value)
                logger.info(
                    f"Transfer successful: {amount} SOL from {self.wallet_address} to {to_address}"
                )
                logger.info(f"Transaction signature: {tx_signature}")

                return {
                    "success": True,
                    "transaction_id": tx_signature,
                    "from_address": self.wallet_address,
                    "to_address": to_address,
                    "amount_sol": amount,
                    "amount_lamports": amount_lamports,
                }
            else:
                return {"error": "Transaction failed to send"}

        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return handle_error_gracefully(
                e, {"operation": "transfer_sol", "to_address": to_address, "amount": amount}
            )

    @rate_limit("solana_rpc")
    @retry_with_backoff(max_retries=2)
    @log_execution()
    async def get_token_accounts(self, address: Optional[str] = None) -> Dict[str, Any]:
        """Get token accounts for an address."""
        try:
            target_address = address or self.wallet_address
            if not target_address:
                return {"error": "No address provided and no wallet configured"}

            # Convert address to Pubkey
            pubkey = Pubkey.from_string(target_address)

            # Get token accounts by owner using jsonParsed encoding
            from solana.rpc.commitment import Commitment

            from solana.rpc.types import TokenAccountOpts

            response = await self.client.get_token_accounts_by_owner(
                pubkey,
                TokenAccountOpts(
                    program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
                ),
                commitment=Commitment("confirmed"),
            )

            accounts = []
            if response.value:
                for account_info in response.value:
                    try:
                        # Use jsonParsed data instead of manual byte parsing
                        account_data = account_info.account.data
                        if hasattr(account_data, "parsed"):
                            parsed_data = account_data.parsed
                        else:
                            # Handle raw data case
                            parsed_data = None
                        if parsed_data and "info" in parsed_data:
                            info = parsed_data["info"]

                            accounts.append(
                                {
                                    "account": str(account_info.pubkey),
                                    "mint": info.get("mint", ""),
                                    "amount": int(info.get("tokenAmount", {}).get("amount", 0)),
                                    "decimals": int(info.get("tokenAmount", {}).get("decimals", 9)),
                                    "uiAmount": float(
                                        info.get("tokenAmount", {}).get("uiAmount", 0)
                                    ),
                                }
                            )
                    except Exception as parse_error:
                        logger.warning(f"Failed to parse token account: {parse_error}")
                        continue

            logger.info(f"Retrieved {len(accounts)} token accounts for {target_address}")
            return {"address": target_address, "token_accounts": accounts}

        except Exception as e:
            logger.error(f"Failed to get token accounts: {e}")
            return {"error": str(e)}

    @rate_limit("solana_rpc")
    @retry_with_backoff(max_retries=2)
    @log_execution()
    async def get_token_metadata(self, mint_address: str) -> Dict[str, Any]:
        """Get comprehensive token metadata using Helius getAsset method."""
        try:
            # Use Helius getAsset method for comprehensive token data
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAsset",
                "params": {"id": mint_address},
            }

            session = await get_session()
            async with session.post(
                self.rpc_url, json=payload, headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    if "result" in data and data["result"]:
                        asset = data["result"]
                        content = asset.get("content", {})

                        logger.info(f"Retrieved comprehensive token data for {mint_address}")
                        return {
                            "success": True,
                            "mint": mint_address,
                            "name": content.get("metadata", {}).get("name", "Unknown"),
                            "symbol": content.get("metadata", {}).get("symbol", "Unknown"),
                            "description": content.get("metadata", {}).get("description", ""),
                            "image": content.get("files", [{}])[0].get("uri", "")
                            if content.get("files")
                            else "",
                            "supply": asset.get("supply", {}),
                            "creators": asset.get("creators", []),
                            "ownership": asset.get("ownership", {}),
                            "token_info": asset.get("token_info", {}),
                            "mutable": asset.get("mutable", False),
                            "burnt": asset.get("burnt", False),
                        }
                    else:
                        return {"error": f"Asset not found for mint: {mint_address}"}
                else:
                    error_text = await response.text()
                    return {"error": f"RPC error {response.status}: {error_text}"}

        except Exception as e:
            logger.error(f"Failed to get token metadata: {e}")
            return {"error": str(e)}


def create_solana_tools(solana_tools: SolanaTools, agent=None) -> list[Tool]:
    """Create Solana tool instances."""

    async def handle_get_balance(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("get_balance", args)
        address = validated_args.get("address")

        # Use agent cache if available and no specific address requested
        if agent and not address:
            cached_balance = agent.get_cached_balance()
            if cached_balance:
                return cached_balance

        # Fetch fresh data
        result = await solana_tools.get_balance(address)

        # Cache the result if no specific address (using default wallet)
        if agent and not address and "error" not in result:
            agent.cache_balance_data(result)

        return result

    async def handle_transfer_sol(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("transfer_sol", args)
        result = await solana_tools.transfer_sol(
            validated_args["to_address"], validated_args["amount"]
        )

        # Invalidate balance cache after transfer
        if agent and "success" in result:
            agent.invalidate_balance_cache()

        return result

    async def handle_get_token_data(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("get_token_data", args)
        mint = validated_args["address"]

        # Check agent cache first
        if agent:
            cached_metadata = agent.get_cached_token_metadata(mint)
            if cached_metadata:
                return cached_metadata

        # Fetch fresh data
        result = await solana_tools.get_token_metadata(mint)

        # Cache the result
        if agent and "error" not in result:
            agent.cache_token_metadata(mint, result)

        return result

    tools = [
        Tool(
            spec=ToolSpec(
                name="get_balance",
                description="Get comprehensive wallet information including SOL balance, all SPL token balances, and wallet address. Returns complete portfolio overview in one call.",
                input_schema={
                    "name": "get_balance",
                    "description": "Get complete wallet balance (SOL + all tokens)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "string",
                                "description": "Optional: specific address to check (uses configured wallet if not provided)",
                            }
                        },
                        "required": [],
                    },
                },
            ),
            handler=handle_get_balance,
        ),
        Tool(
            spec=ToolSpec(
                name="transfer_sol",
                description="Transfer SOL from the configured wallet to another address",
                input_schema={
                    "name": "transfer_sol",
                    "description": "Transfer SOL to another address",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to_address": {"type": "string", "description": "Destination address"},
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to transfer",
                                "minimum": 0.001,
                                "maximum": 1000,
                            },
                        },
                        "required": ["to_address", "amount"],
                    },
                },
            ),
            handler=handle_transfer_sol,
        ),
        Tool(
            spec=ToolSpec(
                name="get_token_data",
                description="Get metadata and supply information for a Solana token",
                input_schema={
                    "name": "get_token_data",
                    "description": "Get token metadata",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "address": {"type": "string", "description": "Token mint address"}
                        },
                        "required": ["address"],
                    },
                },
            ),
            handler=handle_get_token_data,
        ),
    ]

    return tools
