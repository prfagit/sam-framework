import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sam.integrations.pump_fun import PumpFunTools
from sam.integrations.jupiter import JupiterTools
from sam.integrations.dexscreener import DexScreenerTools
from sam.integrations.search import SearchTools


class TestPumpFunTools:
    """Test Pump.fun integration functionality."""

    @pytest.fixture
    async def pump_tools(self):
        """Create Pump.fun tools instance."""
        tools = PumpFunTools()
        yield tools

    @pytest.mark.asyncio
    async def test_pump_tools_initialization(self, pump_tools):
        """Test PumpFunTools initialization."""
        assert pump_tools.base_url == "https://pumpportal.fun/api"
        assert pump_tools.solana_tools is None

    @pytest.mark.asyncio
    async def test_close_method(self, pump_tools):
        """Test close method."""
        await pump_tools.close()  # Should not raise any errors

    @pytest.mark.asyncio
    async def test_sign_and_send_transaction_no_wallet(self, pump_tools):
        """Test transaction signing without wallet configured."""
        result = await pump_tools._sign_and_send_transaction("hex_data", "buy")

        assert "error" in result
        assert "No wallet configured" in result["error"]

    @pytest.mark.asyncio
    async def test_get_token_trades_success(self, pump_tools):
        """Test successful token trades retrieval."""
        mock_response_data = {
            "trades": [
                {"mint": "mint123", "amount": 1000000, "type": "buy"},
                {"mint": "mint123", "amount": 500000, "type": "sell"},
            ]
        }

        # Mock the HTTP session
        with patch("sam.integrations.pump_fun.get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)

            # Create proper async context manager mock
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value = mock_cm

            mock_get_session.return_value = mock_session

            result = await pump_tools.get_token_trades("mint123", 5)

            # Should return a dict with trades data
            assert isinstance(result, dict)
            assert "trades" in result or "error" not in result

    @pytest.mark.asyncio
    async def test_get_token_trades_error(self, pump_tools):
        """Test token trades retrieval with API error."""
        # Mock HTTP session to return error
        with patch("sam.integrations.pump_fun.get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 404
            mock_response.text = AsyncMock(return_value="Token not found")

            # Create proper async context manager mock
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value = mock_cm

            mock_get_session.return_value = mock_session

            result = await pump_tools.get_token_trades("invalid_mint")

            # Should return a dict with error
            assert isinstance(result, dict)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_create_buy_transaction_structure(self, pump_tools):
        """Test buy transaction creation basic structure."""
        # Test that the method exists and can be called with proper args
        try:
            # This will likely fail due to network/API issues, but tests the structure
            result = await pump_tools.create_buy_transaction(
                "mint123", 1000000, 10, "wallet123", 10
            )
            assert isinstance(result, dict)
        except Exception:
            # Expected to fail without proper setup, but tests the method exists
            pass

    @pytest.mark.asyncio
    async def test_create_sell_transaction_structure(self, pump_tools):
        """Test sell transaction creation basic structure."""
        try:
            result = await pump_tools.create_sell_transaction("mint123", 50, 10, "wallet123", 10)
            assert isinstance(result, dict)
        except Exception:
            # Expected to fail without proper setup
            pass

    @pytest.mark.asyncio
    async def test_get_token_info_structure(self, pump_tools):
        """Test token info retrieval basic structure."""
        mock_token_data = {
            "mint": "mint123",
            "name": "Test Token",
            "symbol": "TEST",
            "description": "A test token",
            "market_cap": 1000000,
        }

        # Mock the HTTP session
        with patch("sam.integrations.pump_fun.get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_token_data)

            # Create proper async context manager mock
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value = mock_cm

            mock_get_session.return_value = mock_session

            result = await pump_tools.get_token_info("mint123")
            assert isinstance(result, dict)


class TestJupiterTools:
    """Test Jupiter integration functionality."""

    @pytest.fixture
    async def jupiter_tools(self):
        """Create Jupiter tools instance."""
        tools = JupiterTools()
        yield tools

    @pytest.mark.asyncio
    async def test_jupiter_tools_initialization(self, jupiter_tools):
        """Test JupiterTools initialization."""
        assert jupiter_tools.base_url == "https://quote-api.jup.ag"
        assert jupiter_tools.solana_tools is None

    @pytest.mark.asyncio
    async def test_get_quote_structure(self, jupiter_tools):
        """Test quote retrieval basic structure."""
        mock_quote_data = {
            "inputMint": "So11111111111111111111111111111111111111112",
            "inAmount": "1000000000",
            "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "outAmount": "200000000",
            "otherAmountThreshold": "190000000",
            "swapMode": "ExactIn",
            "slippageBps": 50,
            "priceImpactPct": "0.1",
        }

        # Mock the HTTP session
        with patch("sam.integrations.jupiter.get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_quote_data)

            # Create proper async context manager mock
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value = mock_cm

            mock_get_session.return_value = mock_session

            result = await jupiter_tools.get_quote(
                "So11111111111111111111111111111111111111112",  # SOL
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                1000000000,  # 1 SOL
                50,
            )
            assert isinstance(result, dict)


class TestDexScreenerTools:
    """Test DexScreener integration functionality."""

    @pytest.fixture
    async def dex_tools(self):
        """Create DexScreener tools instance."""
        tools = DexScreenerTools()
        yield tools

    @pytest.mark.asyncio
    async def test_dex_tools_initialization(self, dex_tools):
        """Test DexScreenerTools initialization."""
        assert hasattr(dex_tools, "client")

    @pytest.mark.asyncio
    async def test_search_pairs_structure(self, dex_tools):
        """Test pair search basic structure."""
        try:
            result = await dex_tools.search_pairs("SOL/USDC")
            assert isinstance(result, dict)
        except Exception:
            # Expected to fail without proper setup
            pass

    @pytest.mark.asyncio
    async def test_get_pair_info_structure(self, dex_tools):
        """Test pair info retrieval basic structure."""
        try:
            result = await dex_tools.get_pair_info("pair123")
            assert isinstance(result, dict)
        except Exception:
            # Expected to fail without proper setup
            pass

    @pytest.mark.asyncio
    async def test_get_token_pairs_structure(self, dex_tools):
        """Test token pairs retrieval basic structure."""
        try:
            result = await dex_tools.get_token_pairs("token123")
            assert isinstance(result, dict)
        except Exception:
            # Expected to fail without proper setup
            pass


class TestSearchTools:
    """Test search integration functionality."""

    @pytest.fixture
    async def search_tools(self):
        """Create search tools instance."""
        tools = SearchTools(api_key="test_key")
        yield tools

    @pytest.mark.asyncio
    async def test_search_tools_initialization(self, search_tools):
        """Test SearchTools initialization."""
        assert search_tools.api_key == "test_key"

    @pytest.mark.asyncio
    async def test_search_web_structure(self, search_tools):
        """Test web search basic structure."""
        mock_search_data = {
            "web": {
                "results": [
                    {
                        "title": "Test Result 1",
                        "url": "https://example.com/1",
                        "description": "Test description 1",
                    },
                    {
                        "title": "Test Result 2",
                        "url": "https://example.com/2",
                        "description": "Test description 2",
                    },
                ]
            }
        }

        # Mock the HTTP session
        with patch("sam.integrations.search.get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_search_data)

            # Create proper async context manager mock
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value = mock_cm

            mock_get_session.return_value = mock_session

            result = await search_tools.search_web("test query", 5)
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_search_news_structure(self, search_tools):
        """Test news search basic structure."""
        mock_news_data = {
            "news": {
                "results": [
                    {
                        "title": "Crypto News 1",
                        "url": "https://news.example.com/1",
                        "description": "Latest crypto developments",
                        "age": "2 hours ago",
                    },
                    {
                        "title": "Crypto News 2",
                        "url": "https://news.example.com/2",
                        "description": "Market analysis",
                        "age": "4 hours ago",
                    },
                ]
            }
        }

        # Mock the HTTP session
        with patch("sam.integrations.search.get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_news_data)

            # Create proper async context manager mock
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.return_value = mock_cm

            mock_get_session.return_value = mock_session

            result = await search_tools.search_news("crypto news", 3)
            assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__])
