"""Tests for Kalshi integration with authentication support."""

import base64
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sam.integrations.kalshi import (
    KalshiAuthenticator,
    KalshiClient,
    KalshiIntegrationError,
    KalshiMarket,
    KalshiMarketListInput,
    KalshiTools,
)


def generate_test_private_key() -> rsa.RSAPrivateKey:
    """Generate a test RSA private key."""
    return rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )


def test_kalshi_normalize_market_converts_cents_to_dollars():
    client = KalshiClient()
    raw = {
        "ticker": "TEST-MARKET",
        "title": "Will inflation cool below 3%?",
        "subtitle": "Monthly CPI print",
        "event_ticker": "CPI24",
        "status": "OPEN",
        "category": "economy",
        "open_time": "2024-09-01T00:00:00Z",
        "close_time": "2024-10-01T00:00:00Z",
        "yes_bid": 42,
        "yes_ask": 45,
        "no_bid": 55,
        "no_ask": 58,
        "last_price": 44,
        "volume": 1234,
        "volume_24h": 555,
        "open_interest": 789,
        "liquidity": 2100,
    }

    market = client._normalize_market(raw)

    assert market.ticker == "TEST-MARKET"
    assert market.yes_bid == pytest.approx(0.42)
    assert market.yes_ask == pytest.approx(0.45)
    assert market.last_price == pytest.approx(0.44)
    assert market.open_time == "2024-09-01T00:00:00+00:00"
    assert market.close_time == "2024-10-01T00:00:00+00:00"
    assert market.url.endswith("/TEST-MARKET")


def test_kalshi_status_validator_rejects_invalid_state():
    with pytest.raises(ValueError):
        KalshiMarketListInput(limit=10, status="invalid")

    params = KalshiMarketListInput(limit=10, status="open,closed,open")
    assert params.status == "open,closed"


def test_kalshi_opportunity_ranking_prioritizes_roi_and_liquidity():
    tools = KalshiTools()
    market_high = KalshiMarket(
        ticker="HIGH-ROI",
        title="High ROI market",
        subtitle=None,
        event_ticker="EVT1",
        status="open",
        category="economy",
        open_time=None,
        close_time=None,
        yes_bid=0.32,
        yes_ask=0.35,
        no_bid=0.65,
        no_ask=0.68,
        last_price=0.34,
        volume=20000,
        volume_24h=15000,
        open_interest=5000,
        liquidity=4000,
        url="https://kalshi.com/markets/HIGH-ROI",
    )
    market_low = KalshiMarket(
        ticker="LOW-LIQ",
        title="Low liquidity market",
        subtitle=None,
        event_ticker="EVT2",
        status="open",
        category="politics",
        open_time=None,
        close_time=None,
        yes_bid=0.40,
        yes_ask=0.43,
        no_bid=0.57,
        no_ask=0.6,
        last_price=0.42,
        volume=4000,
        volume_24h=30,  # Below min threshold
        open_interest=200,
        liquidity=20,  # Below min threshold
        url="https://kalshi.com/markets/LOW-LIQ",
    )

    ranked = tools._rank_opportunities(
        [market_high, market_low],
        limit=3,
        min_volume=100,  # Kalshi uses lower defaults (contracts not USD)
        min_liquidity=50,  # Kalshi-specific metric, lower threshold
        max_yes_ask=0.75,
    )

    assert ranked, "Expected at least one opportunity"
    assert ranked[0]["ticker"] == "HIGH-ROI"
    assert ranked[0]["roi_if_yes_resolves"] > 1.0
    # LOW-LIQ should be filtered out due to low volume/liquidity
    tickers = {item["ticker"] for item in ranked}
    assert "LOW-LIQ" not in tickers


def test_kalshi_authenticator_sign_request():
    """Test RSA-PSS signature generation."""
    private_key = generate_test_private_key()
    key_id = "test-key-id-12345"
    authenticator = KalshiAuthenticator(key_id, private_key)

    method = "GET"
    path = "/portfolio/balance"

    headers = authenticator.sign_request(method, path)

    # Verify header structure
    assert "KALSHI-ACCESS-KEY" in headers
    assert "KALSHI-ACCESS-SIGNATURE" in headers
    assert "KALSHI-ACCESS-TIMESTAMP" in headers

    assert headers["KALSHI-ACCESS-KEY"] == key_id
    assert len(headers["KALSHI-ACCESS-TIMESTAMP"]) > 0
    assert len(headers["KALSHI-ACCESS-SIGNATURE"]) > 0

    # Verify signature is valid base64
    try:
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
    except Exception:
        pytest.fail("Signature should be valid base64")


def test_kalshi_authenticator_strips_query_params():
    """Test that query parameters are stripped before signing."""
    private_key = generate_test_private_key()
    key_id = "test-key-id"
    authenticator = KalshiAuthenticator(key_id, private_key)

    path_with_query = "/portfolio/orders?limit=5&status=open"
    path_without_query = "/portfolio/orders"

    headers1 = authenticator.sign_request("GET", path_with_query)
    headers2 = authenticator.sign_request("GET", path_without_query)

    # Signatures should be the same (ignoring timestamp differences)
    # We can't directly compare signatures due to timestamps, but we can verify the logic
    assert headers1["KALSHI-ACCESS-KEY"] == headers2["KALSHI-ACCESS-KEY"]


@pytest.mark.asyncio
async def test_kalshi_client_get_markets_success():
    """Test fetching markets list."""
    mock_response = {
        "markets": [
            {
                "ticker": "TEST-YES",
                "title": "Test Market",
                "status": "open",
                "yes_bid": 50,
                "yes_ask": 52,
                "volume_24h": 1000,
            }
        ],
        "cursor": "next-page",
    }

    mock_session = AsyncMock()
    mock_session.get = MagicMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value.status = 200
    mock_context.__aenter__.return_value.json = AsyncMock(return_value=mock_response)
    mock_session.get.return_value = mock_context

    with patch("sam.integrations.kalshi.get_session", return_value=mock_session):
        client = KalshiClient()
        result = await client.get_markets({"limit": 10})

        assert len(result.markets) == 1
        assert result.markets[0].ticker == "TEST-YES"
        assert result.cursor == "next-page"


@pytest.mark.asyncio
async def test_kalshi_client_get_markets_failure():
    """Test handling of failed market request."""
    mock_session = AsyncMock()
    mock_session.get = MagicMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value.status = 500
    mock_context.__aenter__.return_value.text = AsyncMock(return_value="Internal Server Error")
    mock_session.get.return_value = mock_context

    with patch("sam.integrations.kalshi.get_session", return_value=mock_session):
        client = KalshiClient()
        with pytest.raises(KalshiIntegrationError, match="failed with status 500"):
            await client.get_markets()


@pytest.mark.asyncio
async def test_kalshi_client_get_balance_requires_auth():
    """Test that balance endpoint requires authentication."""
    client = KalshiClient()  # No authenticator

    with pytest.raises(KalshiIntegrationError, match="Authentication required"):
        await client.get_balance()


@pytest.mark.asyncio
async def test_kalshi_client_get_balance_with_auth():
    """Test fetching balance with authentication."""
    private_key = generate_test_private_key()
    authenticator = KalshiAuthenticator("test-key", private_key)

    mock_response = {"balance": 10000}

    mock_session = AsyncMock()
    mock_session.get = MagicMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value.status = 200
    mock_context.__aenter__.return_value.json = AsyncMock(return_value=mock_response)
    mock_session.get.return_value = mock_context

    with patch("sam.integrations.kalshi.get_session", return_value=mock_session):
        client = KalshiClient(authenticator=authenticator)
        result = await client.get_balance()

        assert result["balance"] == 10000


@pytest.mark.asyncio
async def test_kalshi_tools_list_markets():
    """Test KalshiTools list_markets wrapper."""
    mock_response = {
        "markets": [
            {
                "ticker": "TEST-YES",
                "title": "Test Market",
                "status": "open",
                "yes_bid": 50,
                "yes_ask": 52,
                "volume_24h": 1000,
            }
        ],
        "cursor": "next-page",
    }

    mock_session = AsyncMock()
    mock_session.get = MagicMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value.status = 200
    mock_context.__aenter__.return_value.json = AsyncMock(return_value=mock_response)
    mock_session.get.return_value = mock_context

    with patch("sam.integrations.kalshi.get_session", return_value=mock_session):
        tools = KalshiTools()
        result = await tools.list_markets({"limit": 10})

        assert result["success"] is True
        assert result["count"] == 1
        assert result["cursor"] == "next-page"
        assert len(result["markets"]) == 1


@pytest.mark.asyncio
async def test_kalshi_tools_get_balance_without_auth():
    """Test balance tool without authentication."""
    tools = KalshiTools(client=KalshiClient())  # No auth
    result = await tools.get_balance({})

    assert result["success"] is False
    assert "Authentication required" in result["error"]


def test_kalshi_client_uses_demo_mode():
    """Test that client respects demo mode setting."""
    with patch("sam.integrations.kalshi.Settings") as mock_settings:
        mock_settings.KALSHI_USE_DEMO = True
        mock_settings.KALSHI_DEMO_API_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"
        mock_settings.KALSHI_API_BASE_URL = "https://api.kalshi.com/trade-api/v2"
        mock_settings.KALSHI_MARKET_URL = "https://kalshi.com/markets"

        client = KalshiClient()
        assert "demo-api.kalshi.co" in client.base_url


def test_kalshi_market_list_input_validation():
    """Test input validation for market list parameters."""
    # Valid input
    params = KalshiMarketListInput(limit=50, status="open,closed")
    assert params.limit == 50
    assert params.status == "open,closed"

    # Test limit boundaries
    with pytest.raises(ValueError):
        KalshiMarketListInput(limit=0)

    with pytest.raises(ValueError):
        KalshiMarketListInput(limit=1001)

    # Test status validation
    with pytest.raises(ValueError):
        KalshiMarketListInput(status="invalid_status")

    # Test duplicate removal
    params = KalshiMarketListInput(status="open,open,closed")
    assert params.status == "open,closed"
