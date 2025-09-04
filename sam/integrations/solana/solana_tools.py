from typing import Dict, Any, Optional
import logging
import base58
import json
import asyncio
from decimal import Decimal

from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solana.transaction import Transaction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import VersionedTransaction

from ...core.tools import Tool, ToolSpec
from ...utils.validators import validate_tool_input
from ...utils.decorators import rate_limit, retry_with_backoff, log_execution

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
            except Exception as e:
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
        """Get SOL balance for an address or the configured wallet."""
        try:
            target_address = address or self.wallet_address
            if not target_address:
                return {"error": "No address provided and no wallet configured"}
            
            # Convert address string to Pubkey
            pubkey = Pubkey.from_string(target_address)
            
            # Make real RPC call to get balance
            response = await self.client.get_balance(pubkey)
            
            if response.value is not None:
                balance_lamports = response.value
                balance_sol = balance_lamports / 1e9  # Convert lamports to SOL
                
                logger.info(f"Retrieved balance for {target_address}: {balance_sol} SOL")
                return {
                    "address": target_address,
                    "balance_sol": balance_sol,
                    "balance_lamports": balance_lamports
                }
            else:
                logger.error(f"Failed to get balance for {target_address}")
                return {"error": "Failed to retrieve balance from RPC"}
                    
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return {"error": str(e)}

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
                    lamports=amount_lamports
                )
            )
            
            # Get recent blockhash
            recent_blockhash = await self.client.get_latest_blockhash()
            if not recent_blockhash.value:
                return {"error": "Failed to get recent blockhash"}
            
            # Create and sign transaction
            transaction = Transaction(
                recent_blockhash=recent_blockhash.value.blockhash,
                fee_payer=self.keypair.pubkey()
            )
            transaction.add(transfer_instruction)
            transaction.sign(self.keypair)
            
            # Send transaction
            result = await self.client.send_transaction(
                transaction, 
                opts=TxOpts(skip_preflight=False)
            )
            
            if result.value:
                tx_signature = str(result.value)
                logger.info(f"Transfer successful: {amount} SOL from {self.wallet_address} to {to_address}")
                logger.info(f"Transaction signature: {tx_signature}")
                
                return {
                    "transaction_id": tx_signature,
                    "from_address": self.wallet_address,
                    "to_address": to_address,
                    "amount_sol": amount,
                    "amount_lamports": amount_lamports,
                    "status": "confirmed"
                }
            else:
                return {"error": "Transaction failed to send"}
                
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return {"error": str(e)}

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
            response = await self.client.get_token_accounts_by_owner(
                pubkey,
                {"programId": Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")},
                encoding="jsonParsed"
            )
            
            accounts = []
            if response.value:
                for account_info in response.value:
                    try:
                        # Use jsonParsed data instead of manual byte parsing
                        parsed_data = account_info.account.data.parsed
                        if parsed_data and "info" in parsed_data:
                            info = parsed_data["info"]
                            
                            accounts.append({
                                "account": str(account_info.pubkey),
                                "mint": info.get("mint", ""),
                                "amount": int(info.get("tokenAmount", {}).get("amount", 0)),
                                "decimals": int(info.get("tokenAmount", {}).get("decimals", 9)),
                                "uiAmount": float(info.get("tokenAmount", {}).get("uiAmount", 0))
                            })
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
        """Get metadata for a token."""
        try:
            # Convert mint address to Pubkey
            mint_pubkey = Pubkey.from_string(mint_address)
            
            # Get mint account info
            response = await self.client.get_account_info(mint_pubkey)
            
            if response.value is None:
                return {"error": "Token mint not found"}
            
            # Parse mint data
            mint_data = response.value.data
            if len(mint_data) < 82:  # Minimum mint account size
                return {"error": "Invalid mint account data"}
            
            # Extract mint information
            supply = int.from_bytes(mint_data[36:44], 'little')
            decimals = mint_data[44]
            
            logger.info(f"Retrieved metadata for token {mint_address}")
            return {
                "mint": mint_address,
                "supply": supply,
                "decimals": decimals,
                "formatted_supply": supply / (10 ** decimals)
            }
            
        except Exception as e:
            logger.error(f"Failed to get token metadata: {e}")
            return {"error": str(e)}
    
    async def close(self):
        """Close the RPC client connection."""
        if self.client:
            await self.client.close()


def create_solana_tools(solana_tools: SolanaTools) -> list[Tool]:
    """Create Solana tool instances."""
    
    async def handle_get_balance(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("get_balance", args)
        return await solana_tools.get_balance(validated_args.get("address"))
    
    async def handle_transfer_sol(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("transfer_sol", args)
        return await solana_tools.transfer_sol(
            validated_args["to_address"],
            validated_args["amount"]
        )
    
    async def handle_get_token_data(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("get_token_data", args)
        return await solana_tools.get_token_metadata(validated_args["address"])
    
    tools = [
        Tool(
            spec=ToolSpec(
                name="get_balance",
                description="Get SOL balance for the configured wallet or a specific address",
                input_schema={
                    "name": "get_balance",
                    "description": "Get SOL balance",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "string",
                                "description": "Optional: specific address to check (uses wallet address if not provided)"
                            }
                        },
                        "required": []
                    }
                }
            ),
            handler=handle_get_balance
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
                            "to_address": {
                                "type": "string",
                                "description": "Destination address"
                            },
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to transfer",
                                "minimum": 0.001,
                                "maximum": 1000
                            }
                        },
                        "required": ["to_address", "amount"]
                    }
                }
            ),
            handler=handle_transfer_sol
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
                            "address": {
                                "type": "string",
                                "description": "Token mint address"
                            }
                        },
                        "required": ["address"]
                    }
                }
            ),
            handler=handle_get_token_data
        )
    ]
    
    return tools