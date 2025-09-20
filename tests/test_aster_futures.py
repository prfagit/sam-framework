import json
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from sam.integrations.aster_futures import AsterFuturesClient, create_aster_futures_tools


@pytest.fixture
def client() -> AsterFuturesClient:
    client = AsterFuturesClient(
        api_key="dbefbc809e3e83c283a984c3a1459732ea7db1360ca80c5c2c8867408d28cc83",
        api_secret="2b5eb11e18796d12d88f13dc27dbbd02c2cc51ff7059765ed9821957d82bb4d9",
        default_recv_window=5000,
    )
    client._symbol_filters["SOLUSDT"] = {
        "minQty": Decimal("0.01"),
        "stepSize": Decimal("0.01"),
    }
    return client


def test_signed_params_match_reference_example(client: AsterFuturesClient):
    params = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "quantity": 1,
        "price": 9000,
        "timeInForce": "GTC",
    }

    signed = client._signed_params(  # pylint: disable=protected-access
        params,
        timestamp=1591702613943,
        recv_window=5000,
    )

    assert signed["signature"] == (
        "3c661234138461fcc7a7d8746c6558c9842d4e10870d2ecbedf7777cad694af9"
    )


class DummyResponse:
    def __init__(self, payload: Dict[str, Any], method: str = "POST") -> None:
        self.status = 200
        self._payload = payload
        self.method = method
        self.content_type = "application/json"

    async def text(self) -> str:  # pragma: no cover - simple wrapper
        return json.dumps(self._payload)

    async def __aenter__(self):  # pragma: no cover - context manager boilerplate
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover - context manager
        return False


class DummySession:
    def __init__(self) -> None:
        self.post_calls = []
        self.get_calls = []

    def post(self, url, data=None, headers=None):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        return DummyResponse({"code": 200, "msg": "success"})

    def get(self, url, params=None, headers=None):
        self.get_calls.append({"url": url, "params": params, "headers": headers})
        return DummyResponse({"code": 200, "msg": "success"}, method="GET")


@pytest.mark.asyncio
async def test_place_market_order_sends_hmac_signature(monkeypatch, client: AsterFuturesClient):
    fake_session = DummySession()
    monkeypatch.setattr(
        "sam.integrations.aster_futures.get_session",
        AsyncMock(return_value=fake_session),
    )

    result = await client.place_market_order(
        symbol="SOLUSDT",
        side="BUY",
        quantity=5,
        timestamp=1_700_000_000_000,
        recv_window=10_000,
    )

    assert result["endpoint"] == "/fapi/v1/order"
    assert fake_session.post_calls, "Expected an HTTP POST call"

    call = fake_session.post_calls[0]
    assert call["url"].endswith("/fapi/v1/order")
    assert call["headers"]["X-MBX-APIKEY"] == client.api_key
    data = call["data"]
    assert data["symbol"] == "SOLUSDT"
    assert data["side"] == "BUY"
    assert data["type"] == "MARKET"
    assert data["quantity"] == "5"
    assert "signature" in data


@pytest.mark.asyncio
async def test_account_info_gets_signed(monkeypatch, client: AsterFuturesClient):
    fake_session = DummySession()
    monkeypatch.setattr(
        "sam.integrations.aster_futures.get_session",
        AsyncMock(return_value=fake_session),
    )

    result = await client.get_account_info(timestamp=1_700_000_000_000)

    assert result["endpoint"] == "/fapi/v4/account"
    assert fake_session.get_calls, "Expected a GET call"

    call = fake_session.get_calls[0]
    assert call["url"].endswith("/fapi/v4/account")
    assert call["headers"]["X-MBX-APIKEY"] == client.api_key
    params = call["params"]
    assert params["timestamp"] == "1700000000000"
    assert "signature" in params


@pytest.mark.asyncio
async def test_trade_history_includes_symbol(monkeypatch, client: AsterFuturesClient):
    fake_session = DummySession()
    monkeypatch.setattr(
        "sam.integrations.aster_futures.get_session",
        AsyncMock(return_value=fake_session),
    )

    await client.get_trade_history(
        symbol="solusdt",
        limit=100,
        timestamp=1_700_000_000_000,
        recv_window=5000,
    )

    call = fake_session.get_calls[-1]
    params = call["params"]
    assert params["symbol"] == "SOLUSDT"
    assert params["limit"] == "100"
    assert "signature" in params


@pytest.mark.asyncio
async def test_open_long_with_usd_notional(monkeypatch, client: AsterFuturesClient):
    tools = create_aster_futures_tools(client)
    open_tool = next(tool for tool in tools if tool.spec.name == "aster_open_long")

    monkeypatch.setattr(client, "_public_get", AsyncMock(return_value={"response": {"markPrice": "50"}}))
    monkeypatch.setattr(client, "set_leverage", AsyncMock(return_value={}))
    place_mock = AsyncMock(return_value={"endpoint": "/fapi/v1/order", "status": 200, "response": {}})
    monkeypatch.setattr(client, "place_market_order", place_mock)

    result = await open_tool.handler({"symbol": "SOLUSDT", "usd_notional": 100, "leverage": 10})

    assert result["action"] == "open_long"
    place_mock.assert_awaited()
    kwargs = place_mock.await_args.kwargs
    assert float(kwargs["quantity"]) == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_close_position_no_position_returns_message(monkeypatch, client: AsterFuturesClient):
    tools = create_aster_futures_tools(client)
    close_tool = next(tool for tool in tools if tool.spec.name == "aster_close_position")

    monkeypatch.setattr(
        client,
        "get_position_risk",
        AsyncMock(
            return_value={
                "endpoint": "/fapi/v2/positionRisk",
                "status": 200,
                "response": [
                    {"symbol": "SOLUSDT", "positionSide": "BOTH", "positionAmt": "0"}
                ],
            }
        ),
    )
    place_mock = AsyncMock()
    monkeypatch.setattr(client, "place_market_order", place_mock)

    result = await close_tool.handler({"symbol": "SOLUSDT"})

    assert result["action"] == "close_position"
    assert "No" in result.get("message", "")
    place_mock.assert_not_awaited()
