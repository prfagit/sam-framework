"""Aster Finance futures API client using HMAC authentication."""

from __future__ import annotations

import hashlib
import json
import hmac
import logging
import time
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Any, Dict, List, Optional, Sequence, Mapping, Union
from urllib.parse import urlencode

from aiohttp import ClientResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.tools import Tool, ToolSpec
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)

getcontext().prec = 18


class AsterFuturesClient:
    """Minimal REST client for Aster futures HMAC-signed endpoints."""

    def __init__(
        self,
        *,
        base_url: str = "https://fapi.asterdex.com",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        default_recv_window: int = 5000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.default_recv_window = default_recv_window
        self._symbol_filters: Dict[str, Dict[str, Decimal]] = {}

    def set_credentials(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret

    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def set_leverage(
        self,
        *,
        symbol: str,
        leverage: int,
        timestamp: Optional[int] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = self._signed_params(
            {"symbol": symbol, "leverage": leverage},
            timestamp=timestamp,
            recv_window=recv_window,
        )
        return await self._post("/fapi/v1/leverage", payload)

    async def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Union[float, str],
        position_side: Optional[str] = None,
        reduce_only: Optional[bool] = None,
        timestamp: Optional[int] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": self._stringify(quantity),
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        if reduce_only is not None:
            params["reduceOnly"] = "true" if reduce_only else "false"

        payload = self._signed_params(params, timestamp=timestamp, recv_window=recv_window)
        return await self._post("/fapi/v1/order", payload)

    async def get_position_risk(
        self,
        *,
        symbol: Optional[str] = None,
        timestamp: Optional[int] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        payload = self._signed_params(params, timestamp=timestamp, recv_window=recv_window)
        return await self._get("/fapi/v2/positionRisk", payload)

    async def get_account_info(
        self,
        *,
        timestamp: Optional[int] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = self._signed_params({}, timestamp=timestamp, recv_window=recv_window)
        return await self._get("/fapi/v4/account", payload)

    async def get_account_balance(
        self,
        *,
        timestamp: Optional[int] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = self._signed_params({}, timestamp=timestamp, recv_window=recv_window)
        return await self._get("/fapi/v2/balance", payload)

    async def get_trade_history(
        self,
        *,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        from_id: Optional[int] = None,
        limit: Optional[int] = None,
        timestamp: Optional[int] = None,
        recv_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": symbol.upper()}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if from_id is not None:
            params["fromId"] = from_id
        if limit is not None:
            params["limit"] = limit

        payload = self._signed_params(params, timestamp=timestamp, recv_window=recv_window)
        return await self._get("/fapi/v1/userTrades", payload)

    async def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_credentials()
        url = f"{self.base_url}{path}"
        session = await get_session()
        headers = {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with session.post(url, data=data, headers=headers) as response:
            return await self._normalize_response(path, response, request_payload={"data": data})

    async def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_credentials()
        url = f"{self.base_url}{path}"
        session = await get_session()
        headers = {"X-MBX-APIKEY": self.api_key}
        async with session.get(url, params=params, headers=headers) as response:
            return await self._normalize_response(
                path, response, request_payload={"params": params}
            )

    async def _get_symbol_filters(self, symbol: str) -> Dict[str, Decimal]:
        symbol_key = symbol.upper()
        if symbol_key in self._symbol_filters:
            return self._symbol_filters[symbol_key]

        exchange_info = await self._public_get("/fapi/v1/exchangeInfo", {"symbol": symbol_key})
        if "error" in exchange_info:
            raise RuntimeError(f"Failed to fetch exchange info: {exchange_info['error']}")

        data = exchange_info.get("response")
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected exchange info response format")

        symbol_data = None
        for entry in data.get("symbols", []):
            if entry.get("symbol") == symbol_key:
                symbol_data = entry
                break

        if not symbol_data:
            raise RuntimeError(f"Symbol {symbol_key} not found in exchange info")

        filters: Dict[str, Decimal] = {}
        for filt in symbol_data.get("filters", []):
            filter_type = filt.get("filterType")
            if filter_type in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
                if filt.get("minQty") is not None:
                    filters["minQty"] = Decimal(filt["minQty"])
                if filt.get("stepSize") is not None:
                    filters["stepSize"] = Decimal(filt["stepSize"])
            if filter_type in {"MIN_NOTIONAL", "NOTIONAL"} and filt.get("notional") is not None:
                filters["minNotional"] = Decimal(filt["notional"])

        if "stepSize" not in filters:
            filters["stepSize"] = Decimal("1")
        if "minQty" not in filters:
            filters["minQty"] = Decimal("0")

        self._symbol_filters[symbol_key] = filters
        return filters

    async def format_quantity(
        self,
        symbol: str,
        quantity: float,
        mark_price: Optional[float] = None,
    ) -> str:
        filters = await self._get_symbol_filters(symbol)
        step = filters.get("stepSize", Decimal("1"))
        min_qty = filters.get("minQty", Decimal("0"))
        min_notional = filters.get("minNotional")

        qty_dec = Decimal(str(quantity))
        if step > 0:
            step_dec = step
            qty_dec = (qty_dec / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec
            qty_dec = qty_dec.quantize(step_dec)

        # If rounded quantity is below minimum, try rounding UP instead
        if qty_dec <= 0 or qty_dec < min_qty:
            if step > 0:
                from decimal import ROUND_UP
                qty_dec = Decimal(str(quantity))
                qty_dec = (qty_dec / step).to_integral_value(rounding=ROUND_UP) * step
                qty_dec = qty_dec.quantize(step)

        if qty_dec <= 0 or qty_dec < min_qty:
            raise ValueError(
                f"Quantity {qty_dec} is below the minimum allowed {min_qty} for {symbol.upper()}"
            )

        if mark_price is not None and min_notional is not None:
            notional = qty_dec * Decimal(str(mark_price))
            # If notional is below minimum, try to round quantity UP to meet minimum
            if notional < min_notional:
                if step > 0:
                    from decimal import ROUND_UP
                    # Calculate minimum quantity needed to meet notional requirement
                    required_qty = min_notional / Decimal(str(mark_price))
                    qty_dec = (required_qty / step).to_integral_value(rounding=ROUND_UP) * step
                    qty_dec = qty_dec.quantize(step)
                    notional = qty_dec * Decimal(str(mark_price))

            if notional < min_notional:
                raise ValueError(
                    f"Order notional {notional} is below the minimum {min_notional} for {symbol.upper()}. "
                    f"Minimum quantity needed: {(min_notional / Decimal(str(mark_price))).quantize(step)}"
                )

        normalized = qty_dec.normalize()
        quantity_str = format(normalized, "f")
        if "." in quantity_str:
            quantity_str = quantity_str.rstrip("0").rstrip(".")
        if not quantity_str:
            quantity_str = "0"
        if quantity_str == "0":
            raise ValueError("Quantity rounds down to zero; increase amount")

        return quantity_str

    async def _public_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        session = await get_session()
        async with session.get(url, params=params) as response:
            return await self._normalize_response(
                path, response, request_payload={"params": params}
            )

    async def _normalize_response(
        self,
        path: str,
        response: ClientResponse,
        request_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        text = await response.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = text

        if response.status >= 400:
            logger.error(
                "Aster %s %s failed (%s): %s", response.method, path, response.status, data
            )
            return {
                "error": f"HTTP {response.status}",
                "endpoint": path,
                "status": response.status,
                "response": data,
                "request": request_payload,
            }

        return {"endpoint": path, "status": response.status, "response": data}

    def _signed_params(
        self,
        params: Dict[str, Any],
        *,
        timestamp: Optional[int],
        recv_window: Optional[int],
    ) -> Dict[str, Any]:
        self._ensure_credentials()
        prepared = self._prepare_params(params, timestamp=timestamp, recv_window=recv_window)
        query = self._build_query(prepared)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        prepared["signature"] = signature
        return prepared

    def _prepare_params(
        self,
        params: Dict[str, Any],
        *,
        timestamp: Optional[int],
        recv_window: Optional[int],
    ) -> Dict[str, Any]:
        millis = timestamp if timestamp is not None else int(time.time() * 1000)
        window = recv_window if recv_window is not None else self.default_recv_window

        prepared: Dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            prepared[key] = self._stringify(value)

        if window:
            prepared["recvWindow"] = str(window)
        prepared["timestamp"] = str(millis)
        return prepared

    @staticmethod
    def _build_query(params: Dict[str, Any]) -> str:
        return urlencode(params)

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _ensure_credentials(self) -> None:
        if not self.has_credentials():
            raise RuntimeError("Aster API key/secret not configured")


class OpenLongInput(BaseModel):
    symbol: str = Field("SOLUSDT", description="Perpetual symbol to trade")
    quantity: Optional[float] = Field(
        None, gt=0, description="Contract quantity to buy (omit when usd_notional is provided)"
    )
    usd_notional: Optional[float] = Field(
        None,
        gt=0,
        description="Alternative to quantity: dollar notional to deploy based on mark price",
    )
    leverage: Optional[int] = Field(
        10,
        ge=1,
        le=125,
        description="Optional leverage multiplier to set before opening the trade",
    )
    position_side: Optional[str] = Field(
        None,
        description="Position side in hedge mode; leave empty in one-way mode",
    )
    recv_window: Optional[int] = Field(
        None, ge=1000, le=60000, description="Override recvWindow in milliseconds"
    )

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, value: str) -> str:
        return value.upper()

    @field_validator("position_side")
    @classmethod
    def _upper_position_side(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else value

    @model_validator(mode="after")
    def _ensure_quantity_or_notional(self) -> "OpenLongInput":
        if self.quantity is None and self.usd_notional is None:
            raise ValueError("Provide either quantity or usd_notional for the long order")
        return self


class ClosePositionInput(BaseModel):
    symbol: str = Field("SOLUSDT", description="Perpetual symbol to trade")
    quantity: Optional[float] = Field(
        None, gt=0, description="Contracts to close (omit to close entire position)"
    )
    position_side: Optional[str] = Field(
        None,
        description="Position side to close in hedge mode; leave empty in one-way mode",
    )
    reduce_only: bool = Field(True, description="Ensure the order only reduces exposure")
    recv_window: Optional[int] = Field(
        None, ge=1000, le=60000, description="Override recvWindow in milliseconds"
    )

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, value: str) -> str:
        return value.upper()

    @field_validator("position_side")
    @classmethod
    def _upper_position_side(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else value


class PositionCheckInput(BaseModel):
    symbol: Optional[str] = Field(
        None,
        description="Optional symbol filter. If omitted, returns all positions.",
    )
    recv_window: Optional[int] = Field(
        None, ge=1000, le=60000, description="Override recvWindow in milliseconds"
    )

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else value


class AccountInfoInput(BaseModel):
    recv_window: Optional[int] = Field(
        None, ge=1000, le=60000, description="Override recvWindow in milliseconds"
    )


class BalanceInput(BaseModel):
    recv_window: Optional[int] = Field(
        None, ge=1000, le=60000, description="Override recvWindow in milliseconds"
    )


class TradeHistoryInput(BaseModel):
    symbol: str = Field(..., description="Perpetual symbol to query")
    start_time: Optional[int] = Field(None, description="Optional start timestamp (ms)")
    end_time: Optional[int] = Field(None, description="Optional end timestamp (ms)")
    from_id: Optional[int] = Field(None, description="Optional trade id offset")
    limit: Optional[int] = Field(None, ge=1, le=1000, description="Number of records to return")
    recv_window: Optional[int] = Field(
        None, ge=1000, le=60000, description="Override recvWindow in milliseconds"
    )

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, value: str) -> str:
        return value.upper()


def create_aster_futures_tools(client: AsterFuturesClient) -> List[Tool]:
    """Expose the minimal trading workflow as SAM tools."""

    def _missing_credentials() -> Dict[str, str]:
        return {
            "error": (
                "Aster API key/secret are not configured. Set ASTER_API_KEY and ASTER_API_SECRET "
                "or store them via secure storage before trading."
            )
        }

    async def handle_open_long(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_credentials():
            return _missing_credentials()

        parsed = OpenLongInput(**args)

        trade_quantity = parsed.quantity
        mark_price: Optional[float] = None
        if trade_quantity is None and parsed.usd_notional is not None:
            mark_resp = await client._public_get(  # pylint: disable=protected-access
                "/fapi/v1/premiumIndex", {"symbol": parsed.symbol}
            )
            if "error" in mark_resp:
                return {
                    "error": "Failed to fetch mark price",
                    "details": mark_resp,
                }
            try:
                resp_payload = mark_resp.get("response")
                if isinstance(resp_payload, Mapping):
                    mark_value = resp_payload.get("markPrice")
                else:
                    mark_value = None
                mark_price = float(mark_value) if mark_value is not None else 0.0
                trade_quantity = parsed.usd_notional / mark_price if mark_price else 0.0
            except (KeyError, TypeError, ValueError):
                return {
                    "error": "Unexpected mark price response",
                    "details": mark_resp,
                }

        if trade_quantity is None or trade_quantity <= 0:
            return {
                "error": "Calculated quantity is invalid; increase usd_notional or provide quantity",
            }

        try:
            formatted_quantity = await client.format_quantity(
                parsed.symbol, trade_quantity, mark_price=mark_price
            )
        except ValueError as exc:
            return {"error": str(exc)}

        leverage_result: Optional[Dict[str, Any]] = None
        if parsed.leverage is not None:
            leverage_result = await client.set_leverage(
                symbol=parsed.symbol,
                leverage=parsed.leverage,
                recv_window=parsed.recv_window,
            )
            if "error" in leverage_result:
                return {
                    "error": "Failed to set leverage",
                    "leverage_response": leverage_result,
                }

        order_result = await client.place_market_order(
            symbol=parsed.symbol,
            side="BUY",
            quantity=formatted_quantity,
            position_side=parsed.position_side,
            recv_window=parsed.recv_window,
        )
        if "error" in order_result:
            if leverage_result:
                order_result.setdefault("leverage_response", leverage_result)
            return order_result

        result = {
            "action": "open_long",
            "order_response": order_result,
            "quantity": formatted_quantity,
        }
        if leverage_result:
            result["leverage_response"] = leverage_result
        return result

    async def handle_close_position(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_credentials():
            return _missing_credentials()

        parsed = ClosePositionInput(**args)
        position_resp = await client.get_position_risk(symbol=parsed.symbol)
        if "error" in position_resp:
            return position_resp

        raw_entries = position_resp.get("response", [])
        if isinstance(raw_entries, Sequence):
            entries = raw_entries
        else:
            entries = []
        target_side = (parsed.position_side or "").upper()

        position_amt = Decimal("0")
        fallback_amt = Decimal("0")
        for record in entries:
            if not isinstance(record, Mapping):
                continue
            if record.get("symbol") != parsed.symbol:
                continue
            side = record.get("positionSide", "BOTH").upper()
            amt = Decimal(record.get("positionAmt", "0"))
            if target_side and side == target_side:
                position_amt = amt
                break
            if not target_side and side == "BOTH":
                position_amt = amt
                break
            if not target_side and amt != 0:
                fallback_amt = amt

        if position_amt == 0 and not target_side:
            position_amt = fallback_amt

        if position_amt == 0:
            return {
                "action": "close_position",
                "message": f"No {parsed.symbol} position to close",
            }

        abs_position = abs(position_amt)
        if parsed.quantity is None:
            trade_quantity_dec = abs_position
        else:
            trade_quantity_dec = Decimal(str(parsed.quantity))
            if trade_quantity_dec > abs_position:
                trade_quantity_dec = abs_position

        if trade_quantity_dec <= 0:
            return {
                "action": "close_position",
                "message": "Specified quantity is zero after adjustments",
            }

        try:
            formatted_quantity = await client.format_quantity(
                parsed.symbol, float(trade_quantity_dec)
            )
        except ValueError as exc:
            return {"error": str(exc)}

        order_side = "SELL" if position_amt > 0 else "BUY"
        if target_side == "SHORT":
            order_side = "BUY"
        elif target_side == "LONG":
            order_side = "SELL"

        order_result = await client.place_market_order(
            symbol=parsed.symbol,
            side=order_side,
            quantity=formatted_quantity,
            position_side=parsed.position_side,
            reduce_only=parsed.reduce_only,
            recv_window=parsed.recv_window,
        )
        if "error" in order_result:
            return order_result
        return {
            "action": "close_position",
            "order_response": order_result,
            "quantity": formatted_quantity,
        }

    async def handle_position_check(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_credentials():
            return _missing_credentials()

        parsed = PositionCheckInput(**args)
        result = await client.get_position_risk(
            symbol=parsed.symbol,
            recv_window=parsed.recv_window,
        )
        if "error" in result:
            return result
        return {"action": "position_check", "positions": result}

    async def handle_account_info(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_credentials():
            return _missing_credentials()

        parsed = AccountInfoInput(**args)
        result = await client.get_account_info(recv_window=parsed.recv_window)
        return {"action": "account_info", "account": result}

    async def handle_account_balance(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_credentials():
            return _missing_credentials()

        parsed = BalanceInput(**args)
        result = await client.get_account_balance(recv_window=parsed.recv_window)
        return {"action": "account_balance", "balances": result}

    async def handle_trade_history(args: Dict[str, Any]) -> Dict[str, Any]:
        if not client.has_credentials():
            return _missing_credentials()

        parsed = TradeHistoryInput(**args)
        result = await client.get_trade_history(
            symbol=parsed.symbol,
            start_time=parsed.start_time,
            end_time=parsed.end_time,
            from_id=parsed.from_id,
            limit=parsed.limit,
            recv_window=parsed.recv_window,
        )
        return {"action": "trade_history", "trades": result}

    return [
        Tool(
            spec=ToolSpec(
                name="aster_account_info",
                description="Fetch detailed account snapshot including balances and positions.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "recv_window": {
                            "type": "integer",
                            "description": "Override recvWindow in ms",
                            "minimum": 1000,
                            "maximum": 60000,
                        }
                    },
                },
            ),
            handler=handle_account_info,
            input_model=AccountInfoInput,
        ),
        Tool(
            spec=ToolSpec(
                name="aster_account_balance",
                description="Retrieve futures wallet balances from Aster.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "recv_window": {
                            "type": "integer",
                            "description": "Override recvWindow in ms",
                            "minimum": 1000,
                            "maximum": 60000,
                        }
                    },
                },
            ),
            handler=handle_account_balance,
            input_model=BalanceInput,
        ),
        Tool(
            spec=ToolSpec(
                name="aster_trade_history",
                description="List recent account trades for a symbol.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Perpetual symbol"},
                        "start_time": {
                            "type": "integer",
                            "description": "Optional start timestamp in ms",
                        },
                        "end_time": {
                            "type": "integer",
                            "description": "Optional end timestamp in ms",
                        },
                        "from_id": {
                            "type": "integer",
                            "description": "Trade identifier offset",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of rows (1-1000)",
                            "minimum": 1,
                            "maximum": 1000,
                        },
                        "recv_window": {
                            "type": "integer",
                            "description": "Override recvWindow in ms",
                            "minimum": 1000,
                            "maximum": 60000,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            handler=handle_trade_history,
            input_model=TradeHistoryInput,
        ),
        Tool(
            spec=ToolSpec(
                name="aster_open_long",
                description="Open a leveraged long position on Aster futures (market order). MUST provide either quantity OR usd_notional parameter.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Perpetual symbol",
                            "default": "SOLUSDT",
                        },
                        "quantity": {
                            "type": "number",
                            "description": "Contract size to buy (use this OR usd_notional)",
                            "minimum": 0.0001,
                        },
                        "usd_notional": {
                            "type": "number",
                            "description": "USD notional amount to deploy (use this OR quantity)",
                            "minimum": 1,
                        },
                        "leverage": {
                            "type": "integer",
                            "description": "Optional leverage multiplier",
                            "minimum": 1,
                            "maximum": 125,
                            "default": 10,
                        },
                        "position_side": {
                            "type": "string",
                            "description": "Position side (only required in hedge mode)",
                        },
                        "recv_window": {
                            "type": "integer",
                            "description": "Override recvWindow in ms",
                            "minimum": 1000,
                            "maximum": 60000,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            handler=handle_open_long,
            input_model=OpenLongInput,
        ),
        Tool(
            spec=ToolSpec(
                name="aster_close_position",
                description="Close or reduce an existing position via market sell.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Perpetual symbol"},
                        "quantity": {
                            "type": "number",
                            "description": "Contracts to sell to reduce exposure (omit to close full position)",
                        },
                        "position_side": {
                            "type": "string",
                            "description": "Position side (LONG/SHORT in hedge mode)",
                        },
                        "reduce_only": {
                            "type": "boolean",
                            "description": "Ensure order only reduces exposure",
                            "default": True,
                        },
                        "recv_window": {
                            "type": "integer",
                            "description": "Override recvWindow in ms",
                            "minimum": 1000,
                            "maximum": 60000,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            handler=handle_close_position,
            input_model=ClosePositionInput,
        ),
        Tool(
            spec=ToolSpec(
                name="aster_position_check",
                description="Fetch current position risk snapshot from Aster futures.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Optional symbol filter (e.g. SOLUSDT)",
                        },
                        "recv_window": {
                            "type": "integer",
                            "description": "Override recvWindow in ms",
                            "minimum": 1000,
                            "maximum": 60000,
                        },
                    },
                },
            ),
            handler=handle_position_check,
            input_model=PositionCheckInput,
        ),
    ]
