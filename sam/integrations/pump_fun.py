import aiohttp
import logging
from typing import Dict, Any, List, Optional

from ..core.tools import Tool, ToolSpec
from ..utils.validators import validate_tool_input
from ..utils.decorators import rate_limit, retry_with_backoff, log_execution

logger = logging.getLogger(__name__)


class PumpFunTools:
    def __init__(self, solana_tools=None):
        self.base_url = "https://pumpportal.fun/api"
        self.session = None
        self.solana_tools = solana_tools  # For transaction signing and sending
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session
    
    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _sign_and_send_transaction(self, transaction_hex: str, action: str) -> Dict[str, Any]:
        """Sign and send a pump.fun transaction with fresh blockhash."""
        if not self.solana_tools or not self.solana_tools.keypair:
            return {
                "error": "No wallet configured for signing transactions"
            }
        
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
                    signed_tx,
                    opts=TxOpts(skip_preflight=True, max_retries=2)
                )
            except Exception as first_attempt_error:
                error_msg = str(first_attempt_error)
                if "blockhash" in error_msg.lower():
                    logger.warning(f"Blockhash error, transaction may be stale: {first_attempt_error}")
                    return {"error": f"Transaction expired (stale blockhash). Please try again."}
                else:
                    logger.warning(f"Preflight skip failed, retrying with preflight: {first_attempt_error}")
                    # If that fails, try with preflight enabled
                    result = await self.solana_tools.client.send_transaction(
                        signed_tx,
                        opts=TxOpts(skip_preflight=False, max_retries=1)
                    )
            
            if result.value:
                tx_signature = str(result.value)
                logger.info(f"Pump.fun {action} transaction executed successfully: {tx_signature}")
                
                return {
                    "success": True,
                    "transaction_id": tx_signature,
                    "action": action
                }
            else:
                logger.error(f"Transaction failed to send - no signature returned")
                return {
                    "error": "Transaction failed: No signature returned"
                }
                
        except Exception as e:
            logger.error(f"Failed to execute pump.fun transaction: {e}")
            return {
                "error": f"Transaction failed: {str(e)}"
            }

    async def get_token_trades(self, mint: str, limit: int = 10) -> Dict[str, Any]:
        """Get recent trades for a token."""
        try:
            session = await self._get_session()
            
            params = {
                "mint": mint,
                "limit": limit
            }
            
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
                    "total_trades": len(data.get("trades", []))
                }
                
        except aiohttp.ClientError as e:
            logger.error(f"Network error getting trades: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting trades: {e}")
            return {"error": str(e)}

    @rate_limit("pump_fun_buy", identifier_key="public_key")
    @retry_with_backoff(max_retries=2)
    @log_execution()
    async def create_buy_transaction(
        self, 
        public_key: str, 
        mint: str, 
        amount: float, 
        slippage: int = 1
    ) -> Dict[str, Any]:
        """Create a buy transaction for a token on pump.fun."""
        try:
            session = await self._get_session()
            
            payload = {
                "publicKey": public_key,
                "action": "buy",
                "mint": mint,
                "denominatedInSol": "true",
                "amount": amount,
                "slippage": slippage,
                "priorityFee": 0.00001
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
                    sign_result.update({
                        "mint": mint,
                        "amount_sol": amount,
                        "slippage": slippage
                    })
                
                return sign_result
                
        except aiohttp.ClientError as e:
            logger.error(f"Network error creating buy transaction: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error creating buy transaction: {e}")
            return {"error": str(e)}

    @rate_limit("pump_fun_sell", identifier_key="public_key")
    @retry_with_backoff(max_retries=2)
    @log_execution()
    async def create_sell_transaction(
        self, 
        public_key: str, 
        mint: str, 
        percentage: int = 100, 
        slippage: int = 1
    ) -> Dict[str, Any]:
        """Create a sell transaction for a token on pump.fun."""
        try:
            session = await self._get_session()
            
            payload = {
                "publicKey": public_key,
                "action": "sell",
                "mint": mint,
                "denominatedInSol": "false",
                "amount": percentage,  # Percentage of holdings to sell
                "slippage": slippage,
                "priorityFee": 0.00001
            }
            
            logger.info(f"Creating sell transaction: {percentage}% of {mint}")
            
            async with session.post(f"{self.base_url}/trade-local", json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Sell transaction creation failed {response.status}: {error_text}")
                    return {"error": f"Transaction creation failed: {error_text}"}
                
                # Response is raw transaction data
                transaction_data = await response.read()
                transaction_hex = transaction_data.hex()
                
                logger.info(f"Sell transaction created successfully for {mint}")
                
                # Sign and send the transaction automatically
                sign_result = await self._sign_and_send_transaction(transaction_hex, "sell")
                
                # Add transaction details to the result
                if "success" in sign_result:
                    sign_result.update({
                        "mint": mint,
                        "percentage": percentage,
                        "slippage": slippage
                    })
                
                return sign_result
                
        except aiohttp.ClientError as e:
            logger.error(f"Network error creating sell transaction: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error creating sell transaction: {e}")
            return {"error": str(e)}

    async def get_token_info(self, mint: str) -> Dict[str, Any]:
        """Get basic information about a token."""
        try:
            session = await self._get_session()
            
            async with session.get(f"{self.base_url}/coin-data/{mint}") as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Token info API error {response.status}: {error_text}")
                    return {"error": f"API error {response.status}: {error_text}"}
                
                data = await response.json()
                
                logger.info(f"Retrieved token info for {mint}")
                return {
                    "mint": mint,
                    "name": data.get("name", "Unknown"),
                    "symbol": data.get("symbol", "Unknown"),
                    "description": data.get("description", ""),
                    "market_cap": data.get("market_cap", 0),
                    "price": data.get("price", 0),
                    "bonding_curve": data.get("bonding_curve", {}),
                    "twitter": data.get("twitter"),
                    "telegram": data.get("telegram"),
                    "website": data.get("website")
                }
                
        except aiohttp.ClientError as e:
            logger.error(f"Network error getting token info: {e}")
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error getting token info: {e}")
            return {"error": str(e)}

    @rate_limit("launch_token", identifier_key="public_key")
    @retry_with_backoff(max_retries=1)  # Be very careful with token launches
    @log_execution(include_args=True)  # Log args for token launches
    async def launch_token(
        self,
        public_key: str,
        name: str,
        symbol: str,
        description: str,
        image_url: str,
        initial_buy_amount: float = 0.01,
        website: str = None,
        twitter: str = None,
        telegram: str = None
    ) -> Dict[str, Any]:
        """Launch a new token on pump.fun - COMPLEX IMPLEMENTATION NEEDED."""
        # TODO: This needs to be implemented properly following the pumplaunchtoken.js pattern:
        # 1. Create keypair for new mint
        # 2. Create metadata account 
        # 3. Create bonding curve PDA
        # 4. Create associated token accounts
        # 5. Build transaction with create + buy instructions
        # 6. Sign with both wallet keypair and mint keypair
        # 7. Send transaction
        
        logger.warning("Token launch not fully implemented - requires complex transaction building")
        return {
            "error": "Token launch feature is not yet fully implemented. This requires building complex Solana transactions with multiple instructions including token creation, metadata creation, and bonding curve setup."
        }


def create_pump_fun_tools(pump_fun_tools: PumpFunTools, agent=None) -> List[Tool]:
    """Create Pump.fun tool instances."""
    
    async def handle_pump_fun_buy(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("pump_fun_buy", args)
        result = await pump_fun_tools.create_buy_transaction(
            validated_args["public_key"],
            validated_args["mint"],
            validated_args["amount"],
            validated_args.get("slippage", 1)
        )
        
        # Invalidate balance cache after successful transaction
        if agent and "success" in result:
            agent.invalidate_balance_cache()
        
        return result
    
    async def handle_pump_fun_sell(args: Dict[str, Any]) -> Dict[str, Any]:
        validated_args = validate_tool_input("pump_fun_sell", args)
        result = await pump_fun_tools.create_sell_transaction(
            validated_args["public_key"],
            validated_args["mint"],
            validated_args.get("percentage", 100),
            validated_args.get("slippage", 1)
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
    
    async def handle_launch_token(args: Dict[str, Any]) -> Dict[str, Any]:
        return await pump_fun_tools.launch_token(
            args.get("public_key", ""),
            args.get("name", ""),
            args.get("symbol", ""),
            args.get("description", ""),
            args.get("image_url", ""),
            args.get("initial_buy_amount", 0.01),
            args.get("website"),
            args.get("twitter"),
            args.get("telegram")
        )
    
    tools = [
        Tool(
            spec=ToolSpec(
                name="pump_fun_buy",
                description="Create a buy transaction for a token on pump.fun",
                input_schema={
                    "name": "pump_fun_buy",
                    "description": "Buy token on pump.fun",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "public_key": {
                                "type": "string",
                                "description": "Your wallet public key"
                            },
                            "mint": {
                                "type": "string",
                                "description": "Token mint address"
                            },
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to spend",
                                "minimum": 0.001,
                                "maximum": 1000
                            },
                            "slippage": {
                                "type": "integer",
                                "description": "Slippage tolerance (1-50%)",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 1
                            }
                        },
                        "required": ["public_key", "mint", "amount"]
                    }
                }
            ),
            handler=handle_pump_fun_buy
        ),
        Tool(
            spec=ToolSpec(
                name="pump_fun_sell",
                description="Create a sell transaction for a token on pump.fun",
                input_schema={
                    "name": "pump_fun_sell",
                    "description": "Sell token on pump.fun",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "public_key": {
                                "type": "string",
                                "description": "Your wallet public key"
                            },
                            "mint": {
                                "type": "string",
                                "description": "Token mint address"
                            },
                            "percentage": {
                                "type": "integer",
                                "description": "Percentage of holdings to sell (1-100%)",
                                "minimum": 1,
                                "maximum": 100,
                                "default": 100
                            },
                            "slippage": {
                                "type": "integer",
                                "description": "Slippage tolerance (1-50%)",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 1
                            }
                        },
                        "required": ["public_key", "mint"]
                    }
                }
            ),
            handler=handle_pump_fun_sell
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
                            "mint": {
                                "type": "string",
                                "description": "Token mint address"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Number of trades to retrieve (1-50)",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 10
                            }
                        },
                        "required": ["mint"]
                    }
                }
            ),
            handler=handle_get_token_trades
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
                            "mint": {
                                "type": "string",
                                "description": "Token mint address"
                            }
                        },
                        "required": ["mint"]
                    }
                }
            ),
            handler=handle_get_pump_token_info
        ),
        Tool(
            spec=ToolSpec(
                name="launch_token",
                description="Launch a new token on pump.fun with metadata and initial buy",
                input_schema={
                    "name": "launch_token",
                    "description": "Launch new token on pump.fun",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "public_key": {
                                "type": "string",
                                "description": "Your wallet public key"
                            },
                            "name": {
                                "type": "string",
                                "description": "Token name",
                                "maxLength": 50
                            },
                            "symbol": {
                                "type": "string",
                                "description": "Token symbol",
                                "maxLength": 10
                            },
                            "description": {
                                "type": "string",
                                "description": "Token description",
                                "maxLength": 500
                            },
                            "image_url": {
                                "type": "string",
                                "description": "URL to token image/logo"
                            },
                            "initial_buy_amount": {
                                "type": "number",
                                "description": "Initial buy amount in SOL",
                                "minimum": 0.001,
                                "maximum": 10.0,
                                "default": 0.01
                            },
                            "website": {
                                "type": "string",
                                "description": "Optional: Token website URL"
                            },
                            "twitter": {
                                "type": "string", 
                                "description": "Optional: Twitter handle (without @)"
                            },
                            "telegram": {
                                "type": "string",
                                "description": "Optional: Telegram channel/group"
                            }
                        },
                        "required": ["public_key", "name", "symbol", "description", "image_url"]
                    }
                }
            ),
            handler=handle_launch_token
        )
    ]
    
    return tools