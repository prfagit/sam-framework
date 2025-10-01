"""Hyperliquid trading and account tools."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ..core.tools import Tool, ToolSpec

try:  # pragma: no cover - guarded import for optional dependency
    from eth_account import Account
    from eth_account.signers.local import LocalAccount
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils.types import Cloid
except ImportError:  # pragma: no cover - handled at runtime via error responses
    Account = None  # type: ignore
    Exchange = None  # type: ignore
    Info = None  # type: ignore
    LocalAccount = None  # type: ignore
    Cloid = None  # type: ignore

logger = logging.getLogger(__name__)


class HyperliquidClient:
    """Minimal async-friendly wrapper around the Hyperliquid Python SDK."""

    def __init__(
        self,
        *,
        base_url: str,
        private_key: Optional[str] = None,
        account_address: Optional[str] = None,
        timeout: Optional[float] = None,
        default_slippage: float = 0.05,
        info: Optional[Any] = None,
        exchange: Optional[Any] = None,
        to_thread: Callable[..., Any] = asyncio.to_thread,
        skip_ws: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_slippage = default_slippage
        self._to_thread = to_thread

        self._wallet: Optional[LocalAccount] = None
        derived_address: Optional[str] = None
        if private_key:
            if Account is None:
                raise RuntimeError(
                    "hyperliquid-python-sdk dependency is missing; install it to enable trading."
                )
            try:
                self._wallet = Account.from_key(private_key)
            except Exception as exc:
                raise ValueError("Invalid Hyperliquid private key") from exc
            derived_address = self._wallet.address

        if exchange is not None and self._wallet is None and private_key:
            # Some callers may pass a mocked exchange but still want derived address
            if Account is not None and derived_address is None:
                wallet = Account.from_key(private_key)
                derived_address = wallet.address

        normalized = account_address or derived_address or ""
        self.account_address: str = normalized.lower()

        self._info = info
        self._skip_ws = skip_ws
        self._exchange = exchange

    def has_account(self) -> bool:
        return bool(self.account_address)

    def has_trading(self) -> bool:
        return self._exchange is not None or self._wallet is not None

    async def user_state(self, dex: str = "") -> Any:
        self._ensure_account()
        return await self._call_info("user_state", self.account_address, dex=dex)

    async def spot_user_state(self) -> Any:
        self._ensure_account()
        return await self._call_info("spot_user_state", self.account_address)

    async def open_orders(self, dex: str = "") -> Any:
        self._ensure_account()
        return await self._call_info("open_orders", self.account_address, dex=dex)

    async def user_fills(self) -> Any:
        self._ensure_account()
        return await self._call_info("user_fills", self.account_address)

    async def user_fills_by_time(
        self,
        *,
        start_time: int,
        end_time: Optional[int] = None,
        aggregate_by_time: bool = False,
    ) -> Any:
        self._ensure_account()
        return await self._call_info(
            "user_fills_by_time",
            self.account_address,
            start_time,
            end_time,
            aggregate_by_time,
        )

    async def market_open(
        self,
        *,
        coin: str,
        is_buy: bool,
        size: float,
        slippage: Optional[float] = None,
        limit_px: Optional[float] = None,
        cloid: Optional[str] = None,
    ) -> Any:
        exchange = self._ensure_exchange()
        kwargs: Dict[str, Any] = {
            "name": coin,
            "is_buy": is_buy,
            "sz": size,
            "slippage": slippage if slippage is not None else self.default_slippage,
        }
        if limit_px is not None:
            kwargs["px"] = limit_px
        if cloid and Cloid is not None:
            kwargs["cloid"] = Cloid.from_str(cloid)
        return await self._call_exchange(exchange, "market_open", **kwargs)

    async def market_close(
        self,
        *,
        coin: str,
        size: Optional[float] = None,
        slippage: Optional[float] = None,
        limit_px: Optional[float] = None,
        cloid: Optional[str] = None,
    ) -> Any:
        exchange = self._ensure_exchange()
        kwargs: Dict[str, Any] = {
            "coin": coin,
            "slippage": slippage if slippage is not None else self.default_slippage,
        }
        if size is not None:
            kwargs["sz"] = size
        if limit_px is not None:
            kwargs["px"] = limit_px
        if cloid and Cloid is not None:
            kwargs["cloid"] = Cloid.from_str(cloid)
        return await self._call_exchange(exchange, "market_close", **kwargs)

    async def cancel_order(
        self,
        *,
        coin: str,
        oid: Optional[int] = None,
        cloid: Optional[str] = None,
    ) -> Any:
        exchange = self._ensure_exchange()
        if cloid:
            if Cloid is None:
                raise RuntimeError("hyperliquid Cloid helper missing; cannot cancel by cloid")
            cloid_obj = Cloid.from_str(cloid)
            return await self._call_exchange(
                exchange, "cancel_by_cloid", name=coin, cloid=cloid_obj
            )
        if oid is None:
            raise ValueError("Provide either oid or cloid to cancel an order")
        return await self._call_exchange(exchange, "cancel", name=coin, oid=oid)

    async def all_mids(self, dex: str = "") -> Any:
        return await self._call_info("all_mids", dex=dex)

    async def get_mid_price(self, coin: str) -> Optional[float]:
        """Get current mid price for a coin using all_mids endpoint."""
        try:
            mids = await self.all_mids()
            if isinstance(mids, dict):
                price_str = mids.get(coin.upper())
                if price_str:
                    return float(price_str)
            if isinstance(mids, list):
                for entry in mids:
                    if isinstance(entry, dict):
                        name = entry.get("name") or entry.get("coin")
                        if isinstance(name, str) and name.upper() == coin.upper():
                            price_val = entry.get("mid") or entry.get("markPx") or entry.get("px")
                            if price_val is not None:
                                return float(price_val)
        except Exception:
            pass
        try:
            metadata = await self.meta()
            if isinstance(metadata, dict):
                coins = metadata.get("coins")
                if isinstance(coins, list):
                    for entry in coins:
                        if (
                            isinstance(entry, dict)
                            and entry.get("name", "").upper() == coin.upper()
                        ):
                            price_val = entry.get("mid") or entry.get("markPx") or entry.get("px")
                            if price_val is not None:
                                return float(price_val)
        except Exception:
            pass
        return None

    async def meta(self, dex: str = "") -> Any:
        return await self._call_info("meta", dex=dex)

    async def get_sz_decimals(self, coin: str) -> int:
        """Get the size decimals for a coin from exchange metadata.
        
        Each asset has a szDecimals field that determines how many decimal places
        the size must be rounded to.
        """
        try:
            meta = await self.meta()
            if isinstance(meta, dict):
                universe = meta.get("universe", [])
                if isinstance(universe, list):
                    for asset_info in universe:
                        if isinstance(asset_info, dict):
                            if asset_info.get("name", "").upper() == coin.upper():
                                return asset_info.get("szDecimals", 0)
            logger.warning(f"szDecimals not found for {coin}, using default 0")
            return 0
        except Exception:
            logger.exception(f"Failed to get szDecimals for {coin}")
            return 0

    async def update_leverage(
        self,
        *,
        leverage: int,
        coin: str,
        is_cross: bool = True,
    ) -> Any:
        exchange = self._ensure_exchange()
        return await self._call_exchange(
            exchange,
            "update_leverage",
            leverage=leverage,
            name=coin,
            is_cross=is_cross,
        )

    def _ensure_account(self) -> None:
        if not self.has_account():
            raise RuntimeError(
                "Hyperliquid account address is not configured. Provide account_address or a private key."
            )

    def _ensure_exchange(self) -> Any:
        if self._exchange is None:
            if self._wallet is None:
                raise RuntimeError("Hyperliquid trading requires a configured private key")
            if Exchange is None:
                raise RuntimeError(
                    "hyperliquid-python-sdk dependency is missing; install it to enable trading."
                )
            self._exchange = Exchange(
                self._wallet,
                base_url=self.base_url,
                account_address=self.account_address or None,
                timeout=self.timeout,
            )
        return self._exchange

    async def _call_info(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        info = self._ensure_info()
        method = getattr(info, method_name)
        if inspect.iscoroutinefunction(method):
            return await method(*args, **kwargs)
        return await self._to_thread(method, *args, **kwargs)

    async def _call_exchange(self, exchange: Any, method_name: str, **kwargs: Any) -> Any:
        method = getattr(exchange, method_name)
        if inspect.iscoroutinefunction(method):
            return await method(**kwargs)
        return await self._to_thread(method, **kwargs)

    def _ensure_info(self) -> Any:
        if self._info is None:
            if Info is None:
                raise RuntimeError(
                    "hyperliquid-python-sdk dependency is missing; install it to enable tools."
                )
            self._info = Info(self.base_url, skip_ws=self._skip_ws, timeout=self.timeout)
        return self._info


class PositionsInput(BaseModel):
    dex: str = Field("", description="Optional builder dex identifier")


class OrdersInput(BaseModel):
    dex: str = Field("", description="Optional builder dex identifier")


class MarketOrderInput(BaseModel):
    coin: str = Field(..., description="Coin name, e.g., SOL")
    side: str = Field(..., description="Trade direction: buy/long or sell/short")
    size: Optional[float] = Field(
        None, gt=0, description="Order size in coin units (use this OR margin+leverage)"
    )
    margin: Optional[float] = Field(
        None, gt=0, description="USD margin to deploy (requires leverage)"
    )
    leverage: Optional[int] = Field(
        None, gt=0, description="Leverage multiplier (requires margin, e.g., 10 for 10x)"
    )
    slippage: Optional[float] = Field(
        None,
        gt=0,
        le=0.5,
        description="Max slippage fraction to compute the aggressive limit price",
    )
    limit_px: Optional[float] = Field(
        None,
        gt=0,
        description="Optional limit price override (skips automatic slippage calc)",
    )
    cloid: Optional[str] = Field(
        None,
        description="Optional client order id (hex string)",
    )

    @field_validator("coin")
    @classmethod
    def _upper_coin(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _normalize_side(self) -> "MarketOrderInput":
        normalized = self.side.lower()
        if normalized not in {"buy", "sell", "long", "short"}:
            raise ValueError("side must be one of buy, sell, long, short")
        self.side = normalized
        # Require either size OR (margin AND leverage)
        if self.size is None and not (self.margin and self.leverage):
            raise ValueError("Provide size OR (margin AND leverage)")
        if self.size and (self.margin or self.leverage):
            raise ValueError("Provide EITHER size OR (margin+leverage), not both")
        return self


class ClosePositionInput(BaseModel):
    coin: str = Field(..., description="Coin name, e.g., SOL")
    size: Optional[float] = Field(
        None,
        gt=0,
        description="Optional size to close; omit to close the full position",
    )
    slippage: Optional[float] = Field(
        None,
        gt=0,
        le=0.5,
        description="Max slippage fraction when constructing the IOC order",
    )
    limit_px: Optional[float] = Field(None, gt=0, description="Optional limit price override")
    cloid: Optional[str] = Field(
        None,
        description="Optional client order id (hex string)",
    )

    @field_validator("coin")
    @classmethod
    def _upper_coin(cls, value: str) -> str:
        return value.upper()


class CancelOrderInput(BaseModel):
    coin: str = Field(..., description="Coin name, e.g., SOL")
    oid: Optional[int] = Field(
        None,
        ge=0,
        description="Order id to cancel. Required if cloid is not provided.",
    )
    cloid: Optional[str] = Field(
        None,
        description="Optional client order id (hex string). Overrides oid when provided.",
    )

    @field_validator("coin")
    @classmethod
    def _upper_coin(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _validate_identifiers(self) -> "CancelOrderInput":
        if not self.oid and not self.cloid:
            raise ValueError("Provide either oid or cloid to cancel an order")
        return self


class FillsInput(BaseModel):
    start_time: Optional[int] = Field(
        None,
        ge=0,
        description="Optional start time in milliseconds",
    )
    end_time: Optional[int] = Field(
        None,
        ge=0,
        description="Optional end time in milliseconds",
    )
    aggregate_by_time: bool = Field(
        False,
        description="Aggregate fills that occur at the same timestamp",
    )

    @model_validator(mode="after")
    def _validate_window(self) -> "FillsInput":
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return self


def create_hyperliquid_tools(client: HyperliquidClient) -> List[Tool]:
    """Construct Hyperliquid tool definitions."""

    def missing_account_response() -> Dict[str, Any]:
        message = (
            "Hyperliquid account address is not configured. Set HYPERLIQUID_PRIVATE_KEY or "
            "HYPERLIQUID_ACCOUNT_ADDRESS (secure storage entry hyperliquid_account_address)."
        )
        return {
            "success": False,
            "error": message,
            "error_detail": {"code": "configuration", "message": message},
        }

    def missing_trading_response() -> Dict[str, Any]:
        message = (
            "Hyperliquid trading is unavailable. Provide a private key via secure storage "
            "(hyperliquid_private_key) or HYPERLIQUID_PRIVATE_KEY environment variable."
        )
        return {
            "success": False,
            "error": message,
            "error_detail": {"code": "configuration", "message": message},
        }

    def _validation_error_response(
        tool_name: str,
        exc: ValidationError,
        *,
        extra_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        missing_fields: List[str] = []
        for err in exc.errors():
            loc = err.get("loc") or ()
            if loc:
                field = loc[-1]
                if isinstance(field, str) and field not in missing_fields:
                    missing_fields.append(field)
        if missing_fields:
            missing_text = ", ".join(sorted(missing_fields))
            message = f"Missing required parameter(s): {missing_text}."
            instructions = f"Call {tool_name} again and include the field(s): {missing_text}."
        else:
            message = extra_message or f"{tool_name} validation failed"
            instructions = f"Call {tool_name} again with the required parameters."
        return {
            "success": False,
            "error": True,
            "category": "validation",
            "title": "Invalid arguments",
            "message": message,
            "details": {
                "missing_fields": missing_fields,
                "errors": exc.errors(),
            },
            "instructions": instructions,
        }

    async def handle_balance(_: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_account():
            return missing_account_response()
        try:
            state = await client.user_state()
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to fetch Hyperliquid balance")
            return {
                "success": False,
                "error": True,
                "category": "execution",
                "message": str(exc),
            }
        margin_summary = {}
        if isinstance(state, dict):
            margin_summary = state.get("marginSummary") or {}
        return {
            "action": "hyperliquid_balance",
            "state": state,
            "balance": margin_summary,
        }

    async def handle_positions(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_account():
            return missing_account_response()
        parsed = PositionsInput(**args)
        try:
            state = await client.user_state(dex=parsed.dex)
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to fetch Hyperliquid user state")
            return {"error": str(exc)}
        return {"action": "hyperliquid_positions", "state": state}

    async def handle_open_orders(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_account():
            return missing_account_response()
        parsed = OrdersInput(**args)
        try:
            orders = await client.open_orders(dex=parsed.dex)
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to fetch Hyperliquid open orders")
            return {"error": str(exc)}
        return {"action": "hyperliquid_open_orders", "orders": orders}

    async def handle_market_order(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_trading():
            return missing_trading_response()
        try:
            parsed = MarketOrderInput(**args)
        except ValidationError as exc:
            return _validation_error_response("hyperliquid_market_order", exc)

        # Get szDecimals for proper size rounding
        sz_decimals = await client.get_sz_decimals(parsed.coin)

        def _round_order_size(value: float, decimals: int) -> float:
            """Round size to the asset's szDecimals."""
            return round(value, decimals)

        min_order_value = 10.0
        min_order_buffer = 0.25
        order_size = parsed.size
        size_for_exchange = order_size
        computed_from_margin = False
        reference_price: Optional[float] = None
        requested_notional: Optional[float] = None
        estimated_notional: Optional[float] = None
        min_notional_enforced = False

        if parsed.margin is not None and parsed.leverage is not None:
            mid_price = await client.get_mid_price(parsed.coin)
            if not mid_price or mid_price <= 0:
                return {
                    "success": False,
                    "error": f"Cannot determine price for {parsed.coin}",
                    "category": "price_unavailable",
                    "message": f"Cannot determine price for {parsed.coin}",
                }

            computed_from_margin = True
            reference_price = float(mid_price)
            # Calculate position notional: margin * leverage = total position value
            requested_notional = parsed.margin * parsed.leverage
            # Calculate position size in coins: notional / price
            raw_size = requested_notional / reference_price
            order_size = _round_order_size(raw_size, sz_decimals)
            estimated_notional = round(order_size * reference_price, 8)

            # Hyperliquid determines margin based on: (size * price) / leverage
            # We send the full position size, and leverage is set separately
            size_for_exchange = order_size

            # Check minimum notional value requirement ($10)
            if estimated_notional < min_order_value:
                # Adjust to meet minimum, maintaining the leverage ratio
                adjusted_size = (min_order_value + min_order_buffer) / reference_price
                size_for_exchange = _round_order_size(adjusted_size, sz_decimals)
                order_size = size_for_exchange
                estimated_notional = round(order_size * reference_price, 8)
                min_notional_enforced = True

            # Set leverage before placing the order
            try:
                await client.update_leverage(
                    leverage=parsed.leverage,
                    coin=parsed.coin,
                    is_cross=True,
                )
            except Exception as exc:  # pragma: no cover - defensive unmarshalling
                logger.exception("Failed to update Hyperliquid leverage")
                return {
                    "success": False,
                    "error": str(exc),
                    "category": "execution",
                    "message": str(exc),
                }

        if order_size is None:
            return {
                "success": False,
                "error": "Order size could not be determined",
                "category": "validation",
                "message": "Provide either size or margin+leverage to determine order size.",
            }

        if size_for_exchange is None:
            # Round the directly-provided size to szDecimals
            size_for_exchange = _round_order_size(order_size, sz_decimals)

        if reference_price is None and order_size is not None:
            # Attempt to fetch reference price for reporting purposes only
            price = await client.get_mid_price(parsed.coin)
            if price:
                reference_price = float(price)
                estimated_notional = round(order_size * reference_price, 8)

        is_buy = parsed.side in {"buy", "long"}
        try:
            response = await client.market_open(
                coin=parsed.coin,
                is_buy=is_buy,
                size=size_for_exchange,
                slippage=parsed.slippage,
                limit_px=parsed.limit_px,
                cloid=parsed.cloid,
            )
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to place Hyperliquid market order")
            return {
                "success": False,
                "error": str(exc),
                "category": "execution",
                "message": str(exc),
            }
        # Calculate actual margin used (for reporting)
        actual_margin_used: Optional[float] = None
        if parsed.leverage and estimated_notional:
            actual_margin_used = round(estimated_notional / parsed.leverage, 2)
        elif parsed.margin:
            actual_margin_used = parsed.margin

        result = {
            "action": "hyperliquid_market_order",
            "coin": parsed.coin,
            "side": parsed.side,
            "size": size_for_exchange,
            "response": response,
        }

        # Add detailed breakdown when computed from margin
        if computed_from_margin:
            result.update({
                "margin_used": actual_margin_used,
                "leverage": parsed.leverage,
                "position_value": estimated_notional,
                "reference_price": reference_price,
                "min_notional_enforced": min_notional_enforced,
            })

        return result

    async def handle_close_position(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_trading():
            return missing_trading_response()
        try:
            parsed = ClosePositionInput(**args)
        except ValidationError as exc:
            return _validation_error_response("hyperliquid_close_position", exc)
        try:
            response = await client.market_close(
                coin=parsed.coin,
                size=parsed.size,
                slippage=parsed.slippage,
                limit_px=parsed.limit_px,
                cloid=parsed.cloid,
            )
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to close Hyperliquid position")
            return {
                "success": False,
                "error": str(exc),
                "category": "execution",
                "message": str(exc),
            }
        return {
            "action": "hyperliquid_close_position",
            "coin": parsed.coin,
            "size": parsed.size,
            "response": response,
        }

    async def handle_cancel_order(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_trading():
            return missing_trading_response()
        try:
            parsed = CancelOrderInput(**args)
        except ValidationError as exc:
            return _validation_error_response("hyperliquid_cancel_order", exc)
        try:
            response = await client.cancel_order(
                coin=parsed.coin, oid=parsed.oid, cloid=parsed.cloid
            )
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to cancel Hyperliquid order")
            return {
                "success": False,
                "error": True,
                "category": "execution",
                "message": str(exc),
            }
        return {
            "action": "hyperliquid_cancel_order",
            "coin": parsed.coin,
            "oid": parsed.oid,
            "cloid": parsed.cloid,
            "response": response,
        }

    async def handle_user_fills(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_account():
            return missing_account_response()
        parsed = FillsInput(**args)
        try:
            if parsed.start_time is not None:
                fills = await client.user_fills_by_time(
                    start_time=parsed.start_time,
                    end_time=parsed.end_time,
                    aggregate_by_time=parsed.aggregate_by_time,
                )
            else:
                fills = await client.user_fills()
        except Exception as exc:  # pragma: no cover - defensive unmarshalling
            logger.exception("Failed to fetch Hyperliquid fills")
            return {"error": str(exc)}
        return {"action": "hyperliquid_user_fills", "fills": fills}

    return [
        Tool(
            spec=ToolSpec(
                name="hyperliquid_balance",
                description="Summarize Hyperliquid margin balances (account value, margin, withdrawable).",
                input_schema={"type": "object", "properties": {}},
            ),
            handler=handle_balance,
        ),
        Tool(
            spec=ToolSpec(
                name="hyperliquid_positions",
                description="Fetch Hyperliquid perpetual account state (positions, margin).",
                input_schema={"type": "object", "properties": {"dex": {"type": "string"}}},
            ),
            handler=handle_positions,
            input_model=PositionsInput,
        ),
        Tool(
            spec=ToolSpec(
                name="hyperliquid_open_orders",
                description="List open orders for the configured Hyperliquid account.",
                input_schema={"type": "object", "properties": {"dex": {"type": "string"}}},
            ),
            handler=handle_open_orders,
            input_model=OrdersInput,
        ),
        Tool(
            spec=ToolSpec(
                name="hyperliquid_market_order",
                description=(
                    "Execute Hyperliquid perpetual market order. "
                    "REQUIRED: coin (e.g. 'SOL'), side ('buy'/'long'/'sell'/'short'). "
                    "THEN provide EITHER: "
                    "1) size (position size in coins, e.g. 0.5 SOL), OR "
                    "2) margin (USD collateral) + leverage (multiplier). "
                    "MARGIN+LEVERAGE LOGIC: Position value = margin × leverage. "
                    "Example: margin=10, leverage=10 → $100 position (uses $10 collateral). "
                    "Size is auto-calculated as: (margin × leverage) / price. "
                    "Minimum position value: $10. "
                    "Examples: "
                    '{"coin": "SOL", "side": "long", "size": 0.5} opens 0.5 SOL, OR '
                    '{"coin": "SOL", "side": "long", "margin": 10, "leverage": 10} opens $100 worth of SOL with $10 margin'
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "coin": {"type": "string", "description": "Coin symbol (SOL, BTC, ETH)"},
                        "side": {"type": "string", "description": "buy/long or sell/short"},
                        "size": {
                            "type": "number",
                            "description": "Position size in coin units (alternative to margin+leverage)",
                        },
                        "margin": {
                            "type": "number",
                            "description": "USD collateral amount (requires leverage). Position value = margin × leverage",
                        },
                        "leverage": {
                            "type": "integer",
                            "description": "Leverage multiplier (requires margin). 10 = 10x leverage",
                        },
                        "slippage": {
                            "type": "number",
                            "description": "Max slippage fraction (default: 0.05 = 5%)",
                        },
                        "limit_px": {"type": "number", "description": "Optional limit price override"},
                        "cloid": {"type": "string", "description": "Optional client order ID (hex)"},
                    },
                    "required": ["coin", "side"],
                },
            ),
            handler=handle_market_order,
        ),
        Tool(
            spec=ToolSpec(
                name="hyperliquid_close_position",
                description="Close an open Hyperliquid position using an IOC market order.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "coin": {"type": "string"},
                        "size": {"type": "number"},
                        "slippage": {"type": "number"},
                        "limit_px": {"type": "number"},
                        "cloid": {"type": "string"},
                    },
                    "required": ["coin"],
                },
            ),
            handler=handle_close_position,
        ),
        Tool(
            spec=ToolSpec(
                name="hyperliquid_cancel_order",
                description="Cancel a resting Hyperliquid order by oid or client order id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "coin": {"type": "string"},
                        "oid": {"type": "integer"},
                        "cloid": {"type": "string"},
                    },
                    "required": ["coin"],
                },
            ),
            handler=handle_cancel_order,
        ),
        Tool(
            spec=ToolSpec(
                name="hyperliquid_user_fills",
                description="Retrieve recent fills for the Hyperliquid account, optionally bounded by time.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "start_time": {"type": "integer"},
                        "end_time": {"type": "integer"},
                        "aggregate_by_time": {"type": "boolean"},
                    },
                },
            ),
            handler=handle_user_fills,
            input_model=FillsInput,
        ),
    ]
