"""EVM blockchain integration for balance checking and token operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from ..core.tools import Tool, ToolSpec
from ..utils.crypto import normalize_evm_private_key

try:  # pragma: no cover - optional dependency
    from web3 import Web3  # type: ignore[import-untyped]
    from web3.exceptions import Web3Exception  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    Web3 = None  # type: ignore[assignment]
    Web3Exception = Exception  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Common token contract addresses (Ethereum mainnet)
TOKEN_CONTRACTS = {
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
}

# ERC-20 token ABI for balance checking
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


class BalanceInput(BaseModel):
    """Input for balance checking operations."""

    address: str = Field(description="Ethereum address to check balance for")
    token_address: Optional[str] = Field(
        default=None,
        description="Token contract address (optional, defaults to ETH native balance)",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate Ethereum address format."""
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("Invalid Ethereum address format")
        return v.lower()

    @field_validator("token_address")
    @classmethod
    def validate_token_address(cls, v: Optional[str]) -> Optional[str]:
        """Validate token contract address format."""
        if v is not None:
            if not v.startswith("0x") or len(v) != 42:
                raise ValueError("Invalid token contract address format")
            return v.lower()
        return v


class TokenInfoInput(BaseModel):
    """Input for token information operations."""

    token_address: str = Field(description="Token contract address")

    model_config = ConfigDict(extra="forbid")

    @field_validator("token_address")
    @classmethod
    def validate_token_address(cls, v: str) -> str:
        """Validate token contract address format."""
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("Invalid token contract address format")
        return v.lower()


class EvmClient:
    """Ethereum client for balance checking and token operations."""

    def __init__(
        self,
        rpc_url: str,
        private_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        if Web3 is None:
            raise RuntimeError(
                "web3.py is required for EVM operations. Install with: pip install web3"
            )

        self.rpc_url = rpc_url
        self.timeout = timeout
        self._web3: Optional[Web3] = None
        self._account_address: Optional[str] = None

        if private_key:
            try:
                normalized_key = normalize_evm_private_key(private_key)
                account = Web3().eth.account.from_key(normalized_key)
                self._account_address = account.address
            except Exception as exc:
                logger.warning(f"Failed to initialize EVM account: {exc}")
                self._account_address = None

    @property
    def web3(self) -> Web3:
        """Get Web3 instance, creating if necessary."""
        if self._web3 is None:
            self._web3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": self.timeout}))
            if not self._web3.is_connected():
                raise RuntimeError(f"Failed to connect to Ethereum RPC: {self.rpc_url}")
        return self._web3

    @property
    def account_address(self) -> Optional[str]:
        """Get the account address if private key is configured."""
        return self._account_address

    async def get_eth_balance(self, address: str) -> Dict[str, Any]:
        """Get ETH balance for an address."""
        try:
            # Convert to checksum address
            checksum_address = self.web3.to_checksum_address(address)
            balance_wei = self.web3.eth.get_balance(checksum_address)
            balance_eth = self.web3.from_wei(balance_wei, "ether")
            return {
                "address": checksum_address,
                "balance_wei": str(balance_wei),
                "balance_eth": float(balance_eth),
                "currency": "ETH",
            }
        except Web3Exception as exc:
            logger.error(f"Failed to get ETH balance for {address}: {exc}")
            return {"error": f"Failed to get ETH balance: {exc}"}

    async def get_token_balance(self, address: str, token_address: str) -> Dict[str, Any]:
        """Get ERC-20 token balance for an address."""
        try:
            # Convert to checksum addresses
            checksum_address = self.web3.to_checksum_address(address)
            checksum_token_address = self.web3.to_checksum_address(token_address)
            
            contract = self.web3.eth.contract(address=checksum_token_address, abi=ERC20_ABI)
            
            # Get balance
            balance_raw = contract.functions.balanceOf(checksum_address).call()
            
            # Get token decimals
            try:
                decimals = contract.functions.decimals().call()
            except Exception:
                decimals = 18  # Default to 18 decimals
            
            # Calculate human-readable balance
            balance_formatted = balance_raw / (10 ** decimals)
            
            # Get token info
            try:
                symbol = contract.functions.symbol().call()
                name = contract.functions.name().call()
            except Exception:
                symbol = "UNKNOWN"
                name = "Unknown Token"
            
            return {
                "address": checksum_address,
                "token_address": checksum_token_address,
                "balance_raw": str(balance_raw),
                "balance_formatted": float(balance_formatted),
                "decimals": decimals,
                "symbol": symbol,
                "name": name,
            }
        except Web3Exception as exc:
            logger.error(f"Failed to get token balance for {address}: {exc}")
            return {"error": f"Failed to get token balance: {exc}"}

    async def get_token_info(self, token_address: str) -> Dict[str, Any]:
        """Get token information (name, symbol, decimals)."""
        try:
            checksum_token_address = self.web3.to_checksum_address(token_address)
            contract = self.web3.eth.contract(address=checksum_token_address, abi=ERC20_ABI)
            
            name = contract.functions.name().call()
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            
            return {
                "token_address": checksum_token_address,
                "name": name,
                "symbol": symbol,
                "decimals": decimals,
            }
        except Web3Exception as exc:
            logger.error(f"Failed to get token info for {token_address}: {exc}")
            return {"error": f"Failed to get token info: {exc}"}

    async def get_multiple_balances(self, address: str, token_addresses: List[str]) -> Dict[str, Any]:
        """Get balances for multiple tokens including ETH."""
        results = {
            "address": address,
            "eth_balance": await self.get_eth_balance(address),
            "token_balances": {},
        }
        
        for token_addr in token_addresses:
            if token_addr.lower() in TOKEN_CONTRACTS.values():
                # Use token symbol as key
                token_symbol = next(
                    symbol for symbol, addr in TOKEN_CONTRACTS.items() 
                    if addr.lower() == token_addr.lower()
                )
                results["token_balances"][token_symbol] = await self.get_token_balance(address, token_addr)
            else:
                # Use address as key
                results["token_balances"][token_addr] = await self.get_token_balance(address, token_addr)
        
        return results


class EvmTools:
    """High-level wrappers for EVM operations."""

    def __init__(self, client: EvmClient) -> None:
        self._client = client

    async def check_eth_balance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check ETH balance for an address."""
        try:
            params = BalanceInput(**args)
        except Exception as exc:
            return {"error": f"Validation failed: {exc}"}

        return await self._client.get_eth_balance(params.address)

    async def check_token_balance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check ERC-20 token balance for an address."""
        try:
            params = BalanceInput(**args)
        except Exception as exc:
            return {"error": f"Validation failed: {exc}"}

        if not params.token_address:
            return {"error": "Token address is required for token balance check"}

        return await self._client.get_token_balance(params.address, params.token_address)

    async def check_usdc_balance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check USDC balance for an address."""
        try:
            params = BalanceInput(**args)
        except Exception as exc:
            return {"error": f"Validation failed: {exc}"}

        usdc_address = TOKEN_CONTRACTS["USDC"]
        return await self._client.get_token_balance(params.address, usdc_address)

    async def get_token_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get token information (name, symbol, decimals)."""
        try:
            params = TokenInfoInput(**args)
        except Exception as exc:
            return {"error": f"Validation failed: {exc}"}

        return await self._client.get_token_info(params.token_address)

    async def check_wallet_balances(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check multiple balances for a wallet (ETH + common tokens)."""
        try:
            params = BalanceInput(**args)
        except Exception as exc:
            return {"error": f"Validation failed: {exc}"}

        # Check ETH and common tokens
        common_tokens = list(TOKEN_CONTRACTS.values())
        return await self._client.get_multiple_balances(params.address, common_tokens)


def create_evm_tools(tools: EvmTools) -> List[Tool]:
    """Create EVM tool definitions."""
    return [
        Tool(
            spec=ToolSpec(
                name="evm_eth_balance",
                description="Check ETH balance for an Ethereum address.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Ethereum address to check balance for",
                        },
                    },
                    "required": ["address"],
                },
                namespace="evm",
            ),
            handler=tools.check_eth_balance,
            input_model=BalanceInput,
        ),
        Tool(
            spec=ToolSpec(
                name="evm_token_balance",
                description="Check ERC-20 token balance for an Ethereum address.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Ethereum address to check balance for",
                        },
                        "token_address": {
                            "type": "string",
                            "description": "Token contract address",
                        },
                    },
                    "required": ["address", "token_address"],
                },
                namespace="evm",
            ),
            handler=tools.check_token_balance,
            input_model=BalanceInput,
        ),
        Tool(
            spec=ToolSpec(
                name="evm_usdc_balance",
                description="Check USDC balance for an Ethereum address (commonly used for x402 payments).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Ethereum address to check USDC balance for",
                        },
                    },
                    "required": ["address"],
                },
                namespace="evm",
            ),
            handler=tools.check_usdc_balance,
            input_model=BalanceInput,
        ),
        Tool(
            spec=ToolSpec(
                name="evm_token_info",
                description="Get token information (name, symbol, decimals) for a contract address.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "token_address": {
                            "type": "string",
                            "description": "Token contract address",
                        },
                    },
                    "required": ["token_address"],
                },
                namespace="evm",
            ),
            handler=tools.get_token_info,
            input_model=TokenInfoInput,
        ),
        Tool(
            spec=ToolSpec(
                name="evm_wallet_balances",
                description="Check multiple balances for a wallet (ETH + USDC, USDT, DAI, WETH).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Ethereum address to check balances for",
                        },
                    },
                    "required": ["address"],
                },
                namespace="evm",
            ),
            handler=tools.check_wallet_balances,
            input_model=BalanceInput,
        ),
    ]
