from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solders.instruction import AccountMeta, Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from ..core.tools import Tool, ToolSpec
from ..utils.error_messages import handle_error_gracefully
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)


class SolanaClientProtocol(Protocol):
    wallet_address: Optional[str]
    keypair: Any

    async def _get_client(self) -> AsyncClient: ...


LAMPORTS_PER_SOL = 1_000_000_000
ACCOUNT_FEE_LAMPORTS = int(0.025506457970688 * LAMPORTS_PER_SOL)

PROGRAM_ID = Pubkey.from_string("URAa3qGD1qVKKqyQrF8iBVZRTwa4Q8RkMd6Gx7u2KL1")
DEX_PUBKEY = Pubkey.from_string("URAbknhQPhFiY92S5iM9nhzoZC5Vkch7S5VERa4PmuV")
DEX_FEES_PUBKEY = Pubkey.from_string("URAfeAaGMoavvTe8vqPwMX6cUvTjq8WMG5c9nFo7Q8j")
METAPLEX_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")


def _string_to_fixed_array(value: str, length: int = 32) -> bytes:
    encoded = value.encode("utf-8", errors="ignore")
    trimmed = encoded[:length]
    padding = b"\x00" * (length - len(trimmed))
    return trimmed + padding


def _read_le_i64(data: bytes) -> int:
    return int.from_bytes(data, byteorder="little", signed=True)


def _read_le_u64(data: bytes) -> int:
    return int.from_bytes(data, byteorder="little", signed=False)


def _extract_base64_data(data: Any) -> bytes:
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return base64.b64decode(data)
    if isinstance(data, Sequence):
        if not data:
            return b""
        return base64.b64decode(data[0])
    if hasattr(data, "data"):
        inner = getattr(data, "data")
        return _extract_base64_data(inner)
    return b""


def _parse_metadata_symbol(raw: bytes) -> str:
    try:
        idx = 0
        if len(raw) < 1 + 32 + 32 + 4:
            return ""
        idx += 1  # key
        idx += 32  # update authority
        idx += 32  # mint

        if len(raw) < idx + 4:
            return ""
        name_len = int.from_bytes(raw[idx : idx + 4], "little")
        idx += 4 + name_len

        if len(raw) < idx + 4:
            return ""
        symbol_len = int.from_bytes(raw[idx : idx + 4], "little")
        idx += 4
        symbol_bytes = raw[idx : idx + symbol_len]
        symbol = symbol_bytes.decode("utf-8", errors="ignore").strip("\x00").strip()
        return symbol
    except Exception as exc:
        logger.debug("Failed to parse metadata symbol: %s", exc)
        return ""


def _calculate_fees(lamports: int, leverage: int) -> Tuple[int, int, int]:
    base_paid = lamports
    base_fee = (base_paid * 200) // 10_000
    leverage_fee = (base_paid * 10 * leverage) // 10_000
    percentage_fee = base_fee + leverage_fee
    account_fee = ACCOUNT_FEE_LAMPORTS
    return base_paid, percentage_fee, account_fee


def _serialize_initialize(
    market_mint: Pubkey,
    market_symbol: str,
    paid_amount: int,
    position_size: int,
    leverage: int,
    position_nonce: int,
    direction: str,
) -> bytes:
    direction_value = 1 if direction.upper() == "LONG" else 0
    payload = bytearray()
    payload.extend(bytes(market_mint))
    payload.extend(_string_to_fixed_array(market_symbol))
    payload.extend(paid_amount.to_bytes(8, "little", signed=False))
    payload.extend(position_size.to_bytes(8, "little", signed=False))
    payload.append(leverage & 0xFF)
    payload.extend(position_nonce.to_bytes(8, "little", signed=False))
    payload.append(direction_value & 0xFF)
    return bytes(payload)


def _serialize_close(position_nonce: int) -> bytes:
    payload = bytearray()
    payload.append(1)  # bool true
    payload.extend(position_nonce.to_bytes(8, "little", signed=False))
    return bytes(payload)


@dataclass
class UranusPosition:
    account: str
    owner: str
    market_mint: str
    market_symbol: str
    entry_price: float
    liquidation_price: float
    paid_amount: float
    position_size: float
    leverage: int
    closed: bool
    position_nonce: int
    pnl: float
    direction: str
    lamports: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account": self.account,
            "owner": self.owner,
            "market_mint": self.market_mint,
            "market_symbol": self.market_symbol,
            "entry_price": self.entry_price,
            "liquidation_price": self.liquidation_price,
            "paid_amount": self.paid_amount,
            "position_size": self.position_size,
            "leverage": self.leverage,
            "closed": self.closed,
            "position_nonce": self.position_nonce,
            "pnl": self.pnl,
            "direction": self.direction,
            "lamports": self.lamports,
        }


class UranusTools:
    def __init__(self, solana_tools: Optional[SolanaClientProtocol] = None) -> None:
        self.solana_tools = solana_tools

    async def close(self) -> None:
        """Provided for interface compatibility."""
        return None

    async def _get_client(self) -> AsyncClient:
        if not self.solana_tools:
            raise ValueError("Solana client is not configured for Uranus tools")
        client = await self.solana_tools._get_client()
        return client

    async def _fetch_market_symbol(self, client: AsyncClient, mint: Pubkey) -> str:
        metadata_pda, _ = Pubkey.find_program_address(
            [b"metadata", bytes(METAPLEX_PROGRAM_ID), bytes(mint)],
            METAPLEX_PROGRAM_ID,
        )
        account_info = await client.get_account_info(metadata_pda)
        if not account_info.value:
            return ""
        raw = _extract_base64_data(account_info.value.data)
        return _parse_metadata_symbol(raw)

    @staticmethod
    def _derive_market_account(mint: Pubkey) -> Pubkey:
        market_pda, _ = Pubkey.find_program_address(
            [b"uranus_market", bytes(mint), b"v1"], PROGRAM_ID
        )
        return market_pda

    @staticmethod
    def _derive_position_address(owner: Pubkey, nonce: int) -> Pubkey:
        position_pda, _ = Pubkey.find_program_address(
            [b"uranus_position", bytes(owner), nonce.to_bytes(8, "little")], PROGRAM_ID
        )
        return position_pda

    def _deserialize_position(self, account: Pubkey, lamports: int, raw: bytes) -> UranusPosition:
        idx = 0
        owner = Pubkey.from_bytes(raw[idx : idx + 32])
        idx += 32
        market_mint = Pubkey.from_bytes(raw[idx : idx + 32])
        idx += 32
        market_symbol_bytes = raw[idx : idx + 32]
        market_symbol = market_symbol_bytes.decode("utf-8", errors="ignore").strip("\x00").strip()
        idx += 32

        entry_price = _read_le_u64(raw[idx : idx + 8]) / LAMPORTS_PER_SOL
        idx += 8
        liquidation_price = _read_le_u64(raw[idx : idx + 8]) / LAMPORTS_PER_SOL
        idx += 8
        paid_amount = _read_le_u64(raw[idx : idx + 8]) / LAMPORTS_PER_SOL
        idx += 8
        position_size = _read_le_u64(raw[idx : idx + 8]) / LAMPORTS_PER_SOL
        idx += 8

        leverage = raw[idx]
        idx += 1
        closed = bool(raw[idx])
        idx += 1
        position_nonce = _read_le_u64(raw[idx : idx + 8])
        idx += 8
        pnl = _read_le_i64(raw[idx : idx + 8]) / LAMPORTS_PER_SOL
        idx += 8
        direction_flag = raw[idx] if idx < len(raw) else 1
        direction = "LONG" if direction_flag == 1 else "SHORT"

        return UranusPosition(
            account=str(account),
            owner=str(owner),
            market_mint=str(market_mint),
            market_symbol=market_symbol,
            entry_price=entry_price,
            liquidation_price=liquidation_price,
            paid_amount=paid_amount,
            position_size=position_size,
            leverage=leverage,
            closed=closed,
            position_nonce=position_nonce,
            pnl=pnl,
            direction=direction,
            lamports=lamports,
        )

    async def create_position(
        self,
        market_mint: str,
        amount_sol: float,
        leverage: int,
        direction: str,
        market_symbol_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.solana_tools or not getattr(self.solana_tools, "keypair", None):
            return {"error": "No wallet configured for Uranus trading"}
        try:
            client = await self._get_client()
            keypair = self.solana_tools.keypair
            owner = keypair.pubkey()

            mint = Pubkey.from_string(market_mint)
            market_symbol = market_symbol_override or ""
            if not market_symbol:
                market_symbol = await self._fetch_market_symbol(client, mint)
            if not market_symbol:
                market_symbol = "URANUS"

            lamports = int(amount_sol * LAMPORTS_PER_SOL)
            if lamports <= 0:
                raise ValueError("amount_sol must convert to at least 1 lamport")

            base_paid, percentage_fee, account_fee = _calculate_fees(lamports, leverage)
            paid_amount = base_paid + percentage_fee + account_fee
            net_base = max(base_paid - percentage_fee - account_fee, 0)
            position_size = net_base * max(leverage, 1)
            position_nonce = int(time.time() * 1000)

            market_account = self._derive_market_account(mint)
            position_pda = self._derive_position_address(owner, position_nonce)

            serialized = _serialize_initialize(
                market_mint=mint,
                market_symbol=market_symbol,
                paid_amount=paid_amount,
                position_size=position_size,
                leverage=leverage,
                position_nonce=position_nonce,
                direction=direction,
            )

            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=owner, is_signer=True, is_writable=True),
                    AccountMeta(pubkey=owner, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=position_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=market_account, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=DEX_PUBKEY, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=DEX_FEES_PUBKEY, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
                ],
                data=bytes([0]) + serialized,
            )

            latest = await client.get_latest_blockhash()
            if not latest.value:
                raise RuntimeError("Failed to fetch recent blockhash")

            message = MessageV0.try_compile(
                payer=owner,
                instructions=[instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=latest.value.blockhash,
            )
            transaction = VersionedTransaction(message, [keypair])
            result = await client.send_transaction(
                transaction, TxOpts(skip_preflight=False, max_retries=2)
            )

            if result.value is None:
                return {"error": "Transaction failed to send"}

            fees_sol = (percentage_fee + account_fee) / LAMPORTS_PER_SOL
            return {
                "transaction_id": str(result.value),
                "position_nonce": position_nonce,
                "position_account": str(position_pda),
                "market_mint": market_mint,
                "direction": direction.upper(),
                "amount_sol": amount_sol,
                "leverage": leverage,
                "fees_sol": fees_sol,
            }
        except Exception as exc:
            logger.error("Failed to create Uranus position: %s", exc)
            return handle_error_gracefully(exc, {"operation": "uranus_open_position"})

    async def close_position(
        self,
        position_nonce: int,
        owner_override: Optional[str] = None,
        position_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.solana_tools or not getattr(self.solana_tools, "keypair", None):
            return {"error": "No wallet configured for Uranus trading"}
        try:
            client = await self._get_client()
            keypair = self.solana_tools.keypair
            owner = Pubkey.from_string(owner_override) if owner_override else keypair.pubkey()
            position_pda = (
                Pubkey.from_string(position_address)
                if position_address
                else self._derive_position_address(owner, position_nonce)
            )

            serialized = _serialize_close(position_nonce)
            instruction = Instruction(
                program_id=PROGRAM_ID,
                accounts=[
                    AccountMeta(pubkey=position_pda, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=owner, is_signer=True, is_writable=True),
                ],
                data=bytes([2]) + serialized,
            )

            latest = await client.get_latest_blockhash()
            if not latest.value:
                raise RuntimeError("Failed to fetch recent blockhash for closing position")

            message = MessageV0.try_compile(
                payer=owner,
                instructions=[instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=latest.value.blockhash,
            )
            transaction = VersionedTransaction(message, [keypair])
            result = await client.send_transaction(
                transaction, TxOpts(skip_preflight=True, max_retries=2)
            )

            if result.value is None:
                return {"error": "Transaction failed to send"}

            return {
                "transaction_id": str(result.value),
                "position_nonce": position_nonce,
                "position_account": str(position_pda),
            }
        except Exception as exc:
            logger.error("Failed to close Uranus position: %s", exc)
            return handle_error_gracefully(exc, {"operation": "uranus_close_position"})

    async def get_market_liquidity(self, market_mint: str) -> Dict[str, Any]:
        try:
            client = await self._get_client()
            mint = Pubkey.from_string(market_mint)
            market_account = self._derive_market_account(mint)
            account_info = await client.get_account_info(market_account)
            if not account_info.value:
                return {"market_mint": market_mint, "liquidity_sol": 0.0, "lamports": 0}
            lamports = account_info.value.lamports
            return {
                "market_mint": market_mint,
                "market_account": str(market_account),
                "liquidity_sol": lamports / LAMPORTS_PER_SOL,
                "lamports": lamports,
            }
        except Exception as exc:
            logger.error("Failed to fetch Uranus market liquidity: %s", exc)
            return handle_error_gracefully(exc, {"operation": "uranus_market_liquidity"})

    async def get_open_positions(
        self,
        *,
        owner: Optional[str] = None,
        market_mint: Optional[str] = None,
        ticker: Optional[str] = None,
        include_closed: bool = False,
    ) -> Dict[str, Any]:
        try:
            client = await self._get_client()
            response = await client.get_program_accounts(
                PROGRAM_ID, encoding="base64", commitment="confirmed"
            )
            accounts = response.value or []
            owner_filter = owner.lower() if owner else None
            mint_filter = market_mint.lower() if market_mint else None
            ticker_filter = ticker.lower() if ticker else None

            positions: List[Dict[str, Any]] = []
            for keyed_account in accounts:
                raw = _extract_base64_data(keyed_account.account.data)
                if not raw:
                    continue
                if len(raw) == 0:
                    continue
                position = self._deserialize_position(
                    account=keyed_account.pubkey, lamports=keyed_account.account.lamports, raw=raw
                )
                if not include_closed and position.closed:
                    continue
                if owner_filter and position.owner.lower() != owner_filter:
                    continue
                if mint_filter and position.market_mint.lower() != mint_filter:
                    continue
                if ticker_filter and ticker_filter not in position.market_symbol.lower():
                    continue
                positions.append(position.to_dict())

            return {"positions": positions, "count": len(positions)}
        except Exception as exc:
            logger.error("Failed to list Uranus positions: %s", exc)
            return handle_error_gracefully(exc, {"operation": "uranus_get_positions"})

    async def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        try:
            session = await get_session()
            params = {"symbol": symbol.upper()}
            async with session.get("https://core.uranus.ag/price", params=params) as response:
                if response.status != 200:
                    text = await response.text()
                    return {
                        "error": f"Failed to fetch Uranus price: {response.status} {text}",
                        "symbol": symbol.upper(),
                    }
                data = await response.json()
                price = data.get("price")
                return {"symbol": symbol.upper(), "price": price}
        except Exception as exc:
            logger.error("Failed to fetch Uranus ticker price: %s", exc)
            return handle_error_gracefully(exc, {"operation": "uranus_get_price"})


def create_uranus_tools(uranus_tools: UranusTools, agent: Optional[Any] = None) -> List[Tool]:
    class UranusOpenPositionInput(BaseModel):
        market_mint: str = Field(..., description="Token mint address for the market")
        amount_sol: float = Field(
            ..., gt=0.0001, le=100.0, description="Amount of SOL to commit to the position"
        )
        leverage: int = Field(1, ge=1, le=10, description="Leverage multiplier (1-10)")
        direction: str = Field("LONG", description="Direction of the trade: LONG or SHORT")
        market_symbol: Optional[str] = Field(
            None,
            description="Optional override for the market symbol (defaults to on-chain metadata)",
        )

        @field_validator("market_mint")
        @classmethod
        def _validate_mint(cls, value: str) -> str:
            if not isinstance(value, str) or len(value) < 32 or len(value) > 44:
                raise ValueError("Invalid market mint address")
            return value

        @field_validator("direction")
        @classmethod
        def _validate_direction(cls, value: str) -> str:
            direction = value.upper()
            if direction not in {"LONG", "SHORT"}:
                raise ValueError("Direction must be LONG or SHORT")
            return direction

    class UranusClosePositionInput(BaseModel):
        position_nonce: int = Field(..., ge=0, description="Nonce used when opening the position")
        position_account: Optional[str] = Field(
            None, description="Optional position account address override"
        )
        owner: Optional[str] = Field(
            None, description="Optional owner address override (defaults to configured wallet)"
        )

        @field_validator("position_account")
        @classmethod
        def _validate_position_account(cls, value: Optional[str]) -> Optional[str]:
            if value is None:
                return value
            if len(value) < 32 or len(value) > 44:
                raise ValueError("Invalid position account address")
            return value

        @field_validator("owner")
        @classmethod
        def _validate_owner(cls, value: Optional[str]) -> Optional[str]:
            if value is None:
                return value
            if len(value) < 32 or len(value) > 44:
                raise ValueError("Invalid owner address")
            return value

    class UranusPositionsInput(BaseModel):
        owner: Optional[str] = Field(None, description="Filter positions by owner address")
        market_mint: Optional[str] = Field(None, description="Filter positions by market mint")
        ticker: Optional[str] = Field(None, description="Filter positions by ticker substring")
        include_closed: bool = Field(False, description="Include closed positions in the result")

        @model_validator(mode="after")
        def _ensure_single_filter(self) -> "UranusPositionsInput":
            filters = [self.owner, self.market_mint, self.ticker]
            if sum(1 for f in filters if f) > 1:
                raise ValueError(
                    "Provide at most one of owner, market_mint, or ticker to filter positions"
                )
            return self

        @field_validator("owner", "market_mint")
        @classmethod
        def _validate_pubkey(cls, value: Optional[str]) -> Optional[str]:
            if value is None:
                return value
            if len(value) < 32 or len(value) > 44:
                raise ValueError("Invalid public key format")
            return value

    class UranusMarketLiquidityInput(BaseModel):
        market_mint: str = Field(..., description="Market mint address to inspect")

        @field_validator("market_mint")
        @classmethod
        def _validate_mint(cls, value: str) -> str:
            if len(value) < 32 or len(value) > 44:
                raise ValueError("Invalid market mint address")
            return value

    class UranusPriceInput(BaseModel):
        symbol: str = Field(..., min_length=1, max_length=16, description="Token ticker symbol")

    async def handle_open_position(args: Dict[str, Any]) -> Dict[str, Any]:
        result = await uranus_tools.create_position(
            market_mint=args["market_mint"],
            amount_sol=args["amount_sol"],
            leverage=args["leverage"],
            direction=args["direction"],
            market_symbol_override=args.get("market_symbol"),
        )
        if agent and result.get("transaction_id"):
            agent.invalidate_balance_cache()
        return result

    async def handle_close_position(args: Dict[str, Any]) -> Dict[str, Any]:
        result = await uranus_tools.close_position(
            position_nonce=args["position_nonce"],
            owner_override=args.get("owner"),
            position_address=args.get("position_account"),
        )
        if agent and result.get("transaction_id"):
            agent.invalidate_balance_cache()
        return result

    async def handle_get_positions(args: Dict[str, Any]) -> Dict[str, Any]:
        return await uranus_tools.get_open_positions(
            owner=args.get("owner"),
            market_mint=args.get("market_mint"),
            ticker=args.get("ticker"),
            include_closed=args.get("include_closed", False),
        )

    async def handle_get_liquidity(args: Dict[str, Any]) -> Dict[str, Any]:
        return await uranus_tools.get_market_liquidity(args["market_mint"])

    async def handle_get_price(args: Dict[str, Any]) -> Dict[str, Any]:
        return await uranus_tools.get_ticker_price(args["symbol"])

    return [
        Tool(
            spec=ToolSpec(
                name="uranus_open_position",
                description="Open a leveraged LONG or SHORT on URANUS.AG using the configured wallet.",
                input_schema={
                    "name": "uranus_open_position",
                    "description": "Create a Uranus leveraged position",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "market_mint": {"type": "string", "description": "Token mint address"},
                            "amount_sol": {
                                "type": "number",
                                "description": "Amount of SOL to use",
                                "minimum": 0.0001,
                                "maximum": 100.0,
                            },
                            "leverage": {
                                "type": "integer",
                                "description": "Leverage multiplier",
                                "minimum": 1,
                                "maximum": 10,
                            },
                            "direction": {
                                "type": "string",
                                "enum": ["LONG", "SHORT"],
                                "description": "Trade direction",
                            },
                            "market_symbol": {
                                "type": "string",
                                "description": "Optional symbol override",
                            },
                        },
                        "required": ["market_mint", "amount_sol", "leverage", "direction"],
                    },
                },
            ),
            handler=handle_open_position,
            input_model=UranusOpenPositionInput,
        ),
        Tool(
            spec=ToolSpec(
                name="uranus_close_position",
                description="Close an existing URANUS.AG position by nonce.",
                input_schema={
                    "name": "uranus_close_position",
                    "description": "Close a Uranus position",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "position_nonce": {
                                "type": "integer",
                                "description": "Nonce used when the position was opened",
                            },
                            "position_account": {
                                "type": "string",
                                "description": "Optional position account address",
                            },
                            "owner": {
                                "type": "string",
                                "description": "Optional owner address override",
                            },
                        },
                        "required": ["position_nonce"],
                    },
                },
            ),
            handler=handle_close_position,
            input_model=UranusClosePositionInput,
        ),
        Tool(
            spec=ToolSpec(
                name="uranus_get_positions",
                description="List Uranus positions with optional owner or market filters.",
                input_schema={
                    "name": "uranus_get_positions",
                    "description": "Retrieve open Uranus positions",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "owner": {"type": "string", "description": "Filter by owner address"},
                            "market_mint": {
                                "type": "string",
                                "description": "Filter by market mint address",
                            },
                            "ticker": {
                                "type": "string",
                                "description": "Filter by ticker substring",
                            },
                            "include_closed": {
                                "type": "boolean",
                                "description": "Include closed positions in result",
                            },
                        },
                    },
                },
            ),
            handler=handle_get_positions,
            input_model=UranusPositionsInput,
        ),
        Tool(
            spec=ToolSpec(
                name="uranus_market_liquidity",
                description="Retrieve liquidity (SOL) for a Uranus market account.",
                input_schema={
                    "name": "uranus_market_liquidity",
                    "description": "Fetch Uranus market liquidity",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "market_mint": {
                                "type": "string",
                                "description": "Market mint address",
                            }
                        },
                        "required": ["market_mint"],
                    },
                },
            ),
            handler=handle_get_liquidity,
            input_model=UranusMarketLiquidityInput,
        ),
        Tool(
            spec=ToolSpec(
                name="uranus_get_price",
                description="Fetch the latest Uranus oracle price for a ticker symbol.",
                input_schema={
                    "name": "uranus_get_price",
                    "description": "Fetch Uranus ticker price",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {
                                "type": "string",
                                "description": "Ticker symbol, e.g. URA",
                            }
                        },
                        "required": ["symbol"],
                    },
                },
            ),
            handler=handle_get_price,
            input_model=UranusPriceInput,
        ),
    ]
