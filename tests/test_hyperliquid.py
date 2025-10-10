import pytest

from sam.integrations.hyperliquid import HyperliquidClient, create_hyperliquid_tools


class StubInfo:
    def __init__(self) -> None:
        self.calls = []

    def user_state(self, address: str, dex: str = ""):
        self.calls.append(("user_state", address, dex))
        return {
            "address": address,
            "dex": dex,
            "positions": [],
            "marginSummary": {
                "accountValue": 125.5,
                "totalMarginUSDC": 75.25,
                "totalMarginUsed": 10.0,
                "totalPositionValue": 50.0,
                "withdrawable": 65.25,
            },
        }

    def open_orders(self, address: str, dex: str = ""):
        self.calls.append(("open_orders", address, dex))
        return {"address": address, "dex": dex, "orders": []}

    def user_fills(self, address: str):
        self.calls.append(("user_fills", address))
        return {"address": address, "fills": []}

    def user_fills_by_time(self, address: str, start_time: int, end_time, aggregate_by_time: bool):
        self.calls.append(("user_fills_by_time", address, start_time, end_time, aggregate_by_time))
        return {"address": address, "fills": [], "start_time": start_time, "end_time": end_time}

    def all_mids(self, dex: str = ""):
        self.calls.append(("all_mids", dex))
        return {"SOL": 200.0}

    def meta(self, dex: str = ""):
        self.calls.append(("meta", dex))
        return {
            "universe": [
                {"name": "SOL", "szDecimals": 1}  # SOL allows 1 decimal place
            ]
        }


class StubExchange:
    def __init__(self) -> None:
        self.calls = []

    def update_leverage(self, **kwargs):
        self.calls.append(("update_leverage", kwargs))
        return {"status": "ok", "request": kwargs}

    def market_open(self, **kwargs):
        self.calls.append(("market_open", kwargs))
        return {"status": "ok", "request": kwargs}

    def market_close(self, **kwargs):
        self.calls.append(("market_close", kwargs))
        return {"status": "ok", "request": kwargs}

    def cancel(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return {"status": "ok", "request": kwargs}

    def cancel_by_cloid(self, **kwargs):
        self.calls.append(("cancel_by_cloid", kwargs))
        return {"status": "ok", "request": kwargs}


@pytest.mark.asyncio
async def test_positions_and_orders_use_info_stub():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    info = StubInfo()
    exchange = StubExchange()
    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        account_address="0xABCDEF",
        info=info,
        exchange=exchange,
        to_thread=fake_to_thread,
    )

    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    positions_result = await tools["hyperliquid_positions"].handler({"dex": ""})
    open_orders_result = await tools["hyperliquid_open_orders"].handler({"dex": ""})

    assert positions_result["state"]["address"] == "0xabcdef"
    assert open_orders_result["orders"]["orders"] == []
    assert ("user_state", "0xabcdef", "") in info.calls
    assert ("open_orders", "0xabcdef", "") in info.calls


@pytest.mark.asyncio
async def test_balance_summarises_margin():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    info = StubInfo()
    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        account_address="0xABCDEF",
        info=info,
        to_thread=fake_to_thread,
    )

    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    result = await tools["hyperliquid_balance"].handler({})
    balance = result["balance"]

    assert balance["accountValue"] == 125.5
    assert balance["totalMarginUSDC"] == 75.25
    assert balance["withdrawable"] == 65.25
    assert ("user_state", "0xabcdef", "") in info.calls


@pytest.mark.asyncio
async def test_market_order_and_close_call_exchange():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        account_address="0xABCDEF",
        info=StubInfo(),
        exchange=StubExchange(),
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    market_payload = {"coin": "SOL", "side": "buy", "size": 0.5, "slippage": 0.1}
    await tools["hyperliquid_market_order"].handler(market_payload)
    exchange_calls = client._exchange.calls  # type: ignore[attr-defined]
    assert exchange_calls[0][0] == "market_open"
    assert exchange_calls[0][1]["name"] == "SOL"
    assert exchange_calls[0][1]["is_buy"] is True
    assert exchange_calls[0][1]["sz"] == 0.5

    close_payload = {"coin": "SOL", "size": 0.5, "slippage": 0.05}
    close_result = await tools["hyperliquid_close_position"].handler(close_payload)
    assert "response" in close_result


@pytest.mark.asyncio
async def test_market_order_with_margin_and_leverage():
    """Test that margin + leverage correctly calculates position size."""

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    info = StubInfo()
    exchange = StubExchange()
    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        account_address="0xABCDEF",
        info=info,
        exchange=exchange,
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    # Test: $10 margin with 10x leverage should open $100 position
    # SOL price is $200 (from StubInfo.all_mids), so size should be 0.5 SOL
    market_payload = {"coin": "SOL", "side": "long", "margin": 10, "leverage": 10}
    result = await tools["hyperliquid_market_order"].handler(market_payload)

    # Verify leverage was set
    leverage_call = exchange.calls[0]
    assert leverage_call[0] == "update_leverage"
    assert leverage_call[1]["leverage"] == 10
    assert leverage_call[1]["name"] == "SOL"
    assert leverage_call[1]["is_cross"] is True

    # Verify market order was placed with correct size
    market_call = exchange.calls[1]
    assert market_call[0] == "market_open"
    assert market_call[1]["name"] == "SOL"
    assert market_call[1]["is_buy"] is True
    # Size should be 0.5 SOL (=$100 at $200/SOL)
    assert market_call[1]["sz"] == 0.5

    # Verify result contains expected fields
    assert result["action"] == "hyperliquid_market_order"
    assert result["coin"] == "SOL"
    assert result["side"] == "long"
    assert result["size"] == 0.5
    assert result["margin_used"] == 10.0  # $10 margin
    assert result["leverage"] == 10
    assert result["position_value"] == 100.0  # $100 position


@pytest.mark.asyncio
async def test_market_order_minimum_notional_enforcement():
    """Test that minimum $10 notional value is enforced."""

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    info = StubInfo()
    exchange = StubExchange()
    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        account_address="0xABCDEF",
        info=info,
        exchange=exchange,
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    # Test: $1 margin with 5x leverage = $5 position (below $10 minimum)
    # Should be adjusted to minimum $10.25
    market_payload = {"coin": "SOL", "side": "long", "margin": 1, "leverage": 5}
    result = await tools["hyperliquid_market_order"].handler(market_payload)

    # Verify minimum was enforced
    assert result["min_notional_enforced"] is True
    assert result["position_value"] >= 10.0  # At least $10


@pytest.mark.asyncio
async def test_cancel_by_cloid_and_fills_by_time():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    info = StubInfo()
    exchange = StubExchange()
    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        account_address="0xABCDEF",
        info=info,
        exchange=exchange,
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    cancel_payload = {"coin": "SOL", "cloid": "0x" + "12" * 16}
    cancel_result = await tools["hyperliquid_cancel_order"].handler(cancel_payload)
    assert "response" in cancel_result
    assert exchange.calls[-1][0] == "cancel_by_cloid"

    fills_payload = {
        "start_time": 1_700_000_000_000,
        "end_time": 1_700_000_100_000,
        "aggregate_by_time": True,
    }
    await tools["hyperliquid_user_fills"].handler(fills_payload)
    assert info.calls[-1][0] == "user_fills_by_time"


@pytest.mark.asyncio
async def test_missing_credentials_return_error():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    client_read_only = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        info=StubInfo(),
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client_read_only)}

    positions = await tools["hyperliquid_positions"].handler({})
    assert "account address" in positions["error"].lower()

    market = await tools["hyperliquid_market_order"].handler(
        {"coin": "SOL", "side": "buy", "size": 1}
    )
    assert "trading" in market["error"].lower()


@pytest.mark.asyncio
async def test_market_order_missing_arguments_returns_validation_error():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        info=StubInfo(),
        exchange=StubExchange(),
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    result = await tools["hyperliquid_market_order"].handler({})

    assert result["success"] is False
    assert result["error"] is True
    assert result["category"] == "validation"
    assert "coin" in result["details"]["missing_fields"]
    assert "Call hyperliquid_market_order again" in result["instructions"]


@pytest.mark.asyncio
async def test_close_position_missing_arguments_returns_validation_error():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        info=StubInfo(),
        exchange=StubExchange(),
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    result = await tools["hyperliquid_close_position"].handler({})

    assert result["success"] is False
    assert result["error"] is True
    assert result["category"] == "validation"
    assert "coin" in result["details"]["missing_fields"]


@pytest.mark.asyncio
async def test_market_order_computes_size_from_margin_and_leverage():
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    info = StubInfo()
    exchange = StubExchange()
    client = HyperliquidClient(
        base_url="https://api.hyperliquid.xyz",
        info=info,
        exchange=exchange,
        to_thread=fake_to_thread,
    )
    tools = {tool.spec.name: tool for tool in create_hyperliquid_tools(client)}

    # Test: $10 margin with 2x leverage on SOL at $200
    # Expected: size = (10 * 2) / 200 = 0.1 SOL
    # Notional after size rounding should remain close to $20
    result = await tools["hyperliquid_market_order"].handler(
        {"coin": "SOL", "side": "long", "margin": 10, "leverage": 2}
    )

    assert result["margin_used"] == 10.0
    assert result["leverage"] == 2
    assert result["reference_price"] == pytest.approx(200.0)
    assert result["position_value"] == pytest.approx(20.0)
    assert result["size"] == pytest.approx(0.1)
    assert result["min_notional_enforced"] is False

    # Minimum order enforcement when requested notional is below $10
    small_result = await tools["hyperliquid_market_order"].handler(
        {"coin": "SOL", "side": "long", "margin": 1, "leverage": 1}
    )

    assert small_result["min_notional_enforced"] is True
    assert small_result["position_value"] >= 10.0
    # With szDecimals=1, 10.25/200 = 0.05125 rounds to 0.1
    assert small_result["size"] == pytest.approx(0.1, rel=1e-3)

    # Verify leverage was set first
    leverage_call = exchange.calls[0]
    assert leverage_call[0] == "update_leverage"
    assert leverage_call[1]["leverage"] == 2
    assert leverage_call[1]["name"] == "SOL"
    assert leverage_call[1]["is_cross"] is True

    # Then the order was placed with the full size (not divided by leverage)
    # Size should be 0.1 SOL (=$20 at $200/SOL, which requires $10 margin at 2x leverage)
    exchange_call = exchange.calls[1]
    assert exchange_call[0] == "market_open"
    assert exchange_call[1]["sz"] == pytest.approx(0.1)
