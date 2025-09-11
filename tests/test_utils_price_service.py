import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock
from sam.utils.price_service import (
    PriceService,
    PriceData,
    get_price_service,
    get_sol_price,
    format_sol_usd,
    sol_to_usd,
    cleanup_price_service
)


class TestPriceData:
    """Test PriceData dataclass functionality."""

    def test_price_data_creation(self):
        """Test PriceData creation and properties."""
        timestamp = time.time()
        price_data = PriceData(
            price_usd=200.50,
            timestamp=timestamp,
            source="jupiter"
        )

        assert price_data.price_usd == 200.50
        assert price_data.timestamp == timestamp
        assert price_data.source == "jupiter"

    def test_price_data_defaults(self):
        """Test PriceData default values."""
        price_data = PriceData(price_usd=150.0, timestamp=time.time())

        assert price_data.source == "jupiter"

    def test_price_data_is_stale_false(self):
        """Test is_stale returns False for fresh data."""
        current_time = time.time()
        price_data = PriceData(price_usd=200.0, timestamp=current_time)

        assert not price_data.is_stale(ttl_seconds=30)

    def test_price_data_is_stale_true(self):
        """Test is_stale returns True for old data."""
        old_time = time.time() - 60  # 60 seconds ago
        price_data = PriceData(price_usd=200.0, timestamp=old_time)

        assert price_data.is_stale(ttl_seconds=30)

    def test_price_data_age_seconds(self):
        """Test age_seconds property."""
        old_time = time.time() - 45
        price_data = PriceData(price_usd=200.0, timestamp=old_time)

        assert abs(price_data.age_seconds - 45) < 1  # Allow small timing difference


class TestPriceService:
    """Test PriceService functionality."""

    def test_price_service_initialization(self):
        """Test PriceService initialization."""
        service = PriceService(cache_ttl=60)

        assert service.cache_ttl == 60
        assert service._price_cache == {}
        assert isinstance(service._lock, asyncio.Lock)
        assert service.COMMON_TOKENS["SOL"] == "So11111111111111111111111111111111111111112"
        assert service.COMMON_TOKENS["USDC"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    @pytest.mark.asyncio
    @patch("sam.utils.price_service.get_session")
    async def test_get_sol_price_usd_jupiter_success(self, mock_get_session):
        """Test successful SOL price fetch from Jupiter."""
        service = PriceService()

        # Mock HTTP session and response
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "data": {
                "So11111111111111111111111111111111111111112": {
                    "price": 215.75
                }
            }
        })
        class _ACM:
            def __init__(self, resp):
                self.resp = resp
            async def __aenter__(self):
                return self.resp
            async def __aexit__(self, exc_type, exc, tb):
                return False

        mock_session.get.return_value = _ACM(mock_response)
        mock_get_session.return_value = mock_session

        with patch.dict("os.environ", {}, clear=True):
            price = await service.get_sol_price_usd()

            assert price == 215.75
            assert "SOL" in service._price_cache
            assert service._price_cache["SOL"].price_usd == 215.75
            assert service._price_cache["SOL"].source == "jupiter"

    @pytest.mark.asyncio
    @patch("sam.utils.price_service.get_session")
    async def test_get_sol_price_usd_dexscreener_success(self, mock_get_session):
        """Test successful SOL price fetch from DexScreener."""
        service = PriceService()

        # Mock HTTP session and response
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "pairs": [
                {
                    "liquidity": {"usd": 1000000},
                    "priceUsd": "210.25"
                }
            ]
        })
        class _ACM:
            def __init__(self, resp):
                self.resp = resp
            async def __aenter__(self):
                return self.resp
            async def __aexit__(self, exc_type, exc, tb):
                return False

        mock_session.get.return_value = _ACM(mock_response)
        mock_get_session.return_value = mock_session

        with patch.dict("os.environ", {"SAM_PRICE_PROVIDER": "dexscreener"}):
            price = await service.get_sol_price_usd()

            assert price == 210.25
            assert service._price_cache["SOL"].source == "dexscreener"

    @pytest.mark.asyncio
    @patch("sam.utils.price_service.get_session")
    async def test_get_sol_price_usd_auto_fallback(self, mock_get_session):
        """Test auto provider with Jupiter failing and DexScreener succeeding."""
        service = PriceService()

        # Mock HTTP session and responses
        mock_session = MagicMock()

        # Jupiter fails
        jupiter_response = AsyncMock()
        jupiter_response.status = 500
        jupiter_response.json = AsyncMock(side_effect=Exception("API Error"))

        # DexScreener succeeds
        dexscreener_response = AsyncMock()
        dexscreener_response.status = 200
        dexscreener_response.json = AsyncMock(return_value={
            "pairs": [{"liquidity": {"usd": 1000000}, "priceUsd": "205.50"}]
        })

        class _ACM:
            def __init__(self, resp):
                self.resp = resp
            async def __aenter__(self):
                return self.resp
            async def __aexit__(self, exc_type, exc, tb):
                return False

        # Return different context managers in sequence
        mock_session.get.side_effect = [
            _ACM(jupiter_response),
            _ACM(dexscreener_response),
        ]
        mock_get_session.return_value = mock_session

        with patch.dict("os.environ", {"SAM_PRICE_PROVIDER": "auto"}):
            price = await service.get_sol_price_usd()

            assert price == 205.50
            assert service._price_cache["SOL"].source == "dexscreener"

    @patch("sam.utils.price_service.get_session")
    async def test_get_sol_price_usd_cache_hit(self, mock_get_session):
        """Test using cached SOL price."""
        service = PriceService()
        cached_time = time.time() - 10  # 10 seconds ago
        service._price_cache["SOL"] = PriceData(
            price_usd=220.0,
            timestamp=cached_time,
            source="cached"
        )

        # Should not make HTTP request
        price = await service.get_sol_price_usd()

        assert price == 220.0
        mock_get_session.assert_not_called()

    @patch("sam.utils.price_service.get_session")
    async def test_get_sol_price_usd_stale_cache(self, mock_get_session):
        """Test using stale cache when API fails."""
        service = PriceService()
        old_time = time.time() - 120  # 2 minutes ago (stale)
        service._price_cache["SOL"] = PriceData(
            price_usd=210.0,
            timestamp=old_time,
            source="stale"
        )

        # Mock API failure
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_session.get.return_value.__aenter__.return_value = mock_response
        mock_get_session.return_value = mock_session

        with patch.object(service, "_get_fallback_sol_price", return_value=215.0):
            price = await service.get_sol_price_usd()

            assert price == 215.0  # Should use fallback, not stale cache

    async def test_get_sol_price_usd_fallback_to_estimate(self):
        """Test fallback to estimated price."""
        service = PriceService()

        # Clear cache and mock API failures
        service._price_cache.clear()

        with patch.object(service, "_get_fallback_sol_price", return_value=215.0) as mock_fallback:
            price = await service.get_sol_price_usd()

            assert price == 215.0
            mock_fallback.assert_called_once()

    async def test_get_fallback_sol_price_with_stale_cache(self):
        """Test fallback price using stale cache."""
        service = PriceService()
        old_time = time.time() - 120
        service._price_cache["SOL"] = PriceData(
            price_usd=208.0,
            timestamp=old_time,
            source="stale"
        )

        price = await service._get_fallback_sol_price()

        assert price == 208.0

    async def test_get_fallback_sol_price_estimate(self):
        """Test fallback price using hardcoded estimate."""
        service = PriceService()
        service._price_cache.clear()

        price = await service._get_fallback_sol_price()

        assert price == 215.0  # Hardcoded estimate

    @pytest.mark.asyncio
    async def test_sol_to_usd_conversion(self):
        """Test SOL to USD conversion."""
        service = PriceService()

        with patch.object(service, "get_sol_price_usd", return_value=200.0):
            usd_value = await service.sol_to_usd(2.5)

            assert usd_value == 500.0

    @pytest.mark.asyncio
    async def test_format_sol_with_usd_zero_amount(self):
        """Test formatting zero SOL amount."""
        service = PriceService()

        result = await service.format_sol_with_usd(0)

        assert result == "0 SOL ($0.00)"

    @pytest.mark.asyncio
    async def test_format_sol_with_usd_large_amount(self):
        """Test formatting large SOL amount."""
        service = PriceService()

        with patch.object(service, "get_sol_price_usd", return_value=200.0):
            result = await service.format_sol_with_usd(5.123456789)

            assert "5.123" in result
            # 5.123456789 * 200 = 1024.691..., rounded to 2 decimals
            assert "$1024.69" in result

    @pytest.mark.asyncio
    async def test_format_sol_with_usd_small_amount(self):
        """Test formatting small SOL amount."""
        service = PriceService()

        with patch.object(service, "get_sol_price_usd", return_value=200.0):
            result = await service.format_sol_with_usd(0.00123456789)

            # Default formatting uses 4 decimals for small SOL values
            assert "0.0012" in result
            assert "$0.247" in result

    @pytest.mark.asyncio
    async def test_format_sol_with_usd_error_handling(self):
        """Test error handling in SOL formatting."""
        service = PriceService()

        with patch.object(service, "get_sol_price_usd", side_effect=Exception("API Error")):
            result = await service.format_sol_with_usd(1.0)

            assert "1.0000 SOL" in result

    @pytest.mark.asyncio
    async def test_format_portfolio_value_success(self):
        """Test portfolio value formatting success."""
        service = PriceService()

        with patch.object(service, "get_sol_price_usd", return_value=180.0):
            result = await service.format_portfolio_value(3.5)

            assert result["sol_balance"] == 3.5
            assert result["sol_usd"] == 630.0
            assert result["total_usd"] == 630.0
            assert "3.5" in result["formatted_sol"]
            assert "$630.00" in result["formatted_total"]
            assert result["sol_price"] == 180.0

    @pytest.mark.asyncio
    async def test_format_portfolio_value_error(self):
        """Test portfolio value formatting with error."""
        service = PriceService()

        with patch.object(service, "get_sol_price_usd", side_effect=Exception("API Error")):
            result = await service.format_portfolio_value(2.0)

            assert result["sol_balance"] == 2.0
            assert result["sol_usd"] == 0.0
            assert result["total_usd"] == 0.0
            assert result["formatted_sol"] == "2.0000 SOL"
            assert result["formatted_total"] == "$0.00"
            assert result["sol_price"] == 0.0

    def test_get_cache_stats(self):
        """Test cache statistics retrieval."""
        service = PriceService()
        current_time = time.time()

        # Add some test data to cache
        service._price_cache["SOL"] = PriceData(
            price_usd=200.0,
            timestamp=current_time,
            source="jupiter"
        )
        service._price_cache["USDC"] = PriceData(
            price_usd=1.0,
            timestamp=current_time - 60,
            source="dexscreener"
        )

        stats = service.get_cache_stats()

        assert stats["cached_tokens"] == 2
        assert stats["cache_ttl"] == 30
        assert "SOL" in stats["tokens"]
        assert "USDC" in stats["tokens"]
        assert stats["tokens"]["SOL"]["price_usd"] == 200.0
        assert stats["tokens"]["SOL"]["source"] == "jupiter"
        assert not stats["tokens"]["SOL"]["is_stale"]

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """Test cache clearing functionality."""
        service = PriceService()
        service._price_cache["SOL"] = PriceData(price_usd=200.0, timestamp=time.time())

        await service.clear_cache()

        assert service._price_cache == {}


class TestGlobalPriceService:
    """Test global price service functions."""

    @pytest.mark.asyncio
    @patch("sam.utils.price_service._price_service_lock")
    async def test_get_price_service_singleton(self, mock_lock):
        """Test global price service singleton pattern."""
        # Reset global state
        import sam.utils.price_service
        sam.utils.price_service._global_price_service = None

        mock_lock.__aenter__ = AsyncMock()
        mock_lock.__aexit__ = AsyncMock()

        service = await get_price_service()

        assert isinstance(service, PriceService)

        # Second call should return same instance
        service2 = await get_price_service()
        assert service2 is service

    @pytest.mark.asyncio
    async def test_cleanup_price_service(self):
        """Test global price service cleanup."""
        # Set up a mock service
        mock_service = MagicMock()
        mock_service.clear_cache = AsyncMock()

        import sam.utils.price_service
        sam.utils.price_service._global_price_service = mock_service

        await cleanup_price_service()

        mock_service.clear_cache.assert_called_once()
        assert sam.utils.price_service._global_price_service is None

    @pytest.mark.asyncio
    async def test_cleanup_price_service_no_service(self):
        """Test cleanup when no global service exists."""
        import sam.utils.price_service
        sam.utils.price_service._global_price_service = None

        # Should not raise exception
        await cleanup_price_service()

    @pytest.mark.asyncio
    @patch("sam.utils.price_service.get_price_service")
    async def test_get_sol_price_convenience(self, mock_get_service):
        """Test get_sol_price convenience function."""
        mock_service = MagicMock()
        mock_service.get_sol_price_usd = AsyncMock(return_value=205.0)
        mock_get_service.return_value = mock_service

        price = await get_sol_price()

        assert price == 205.0
        mock_service.get_sol_price_usd.assert_called_once()

    @pytest.mark.asyncio
    @patch("sam.utils.price_service.get_price_service")
    async def test_format_sol_usd_convenience(self, mock_get_service):
        """Test format_sol_usd convenience function."""
        mock_service = MagicMock()
        mock_service.format_sol_with_usd = AsyncMock(return_value="1.5000 SOL ($300.00)")
        mock_get_service.return_value = mock_service

        result = await format_sol_usd(1.5)

        assert result == "1.5000 SOL ($300.00)"
        mock_service.format_sol_with_usd.assert_called_once_with(1.5)

    @pytest.mark.asyncio
    @patch("sam.utils.price_service.get_price_service")
    async def test_sol_to_usd_convenience(self, mock_get_service):
        """Test sol_to_usd convenience function."""
        mock_service = MagicMock()
        mock_service.sol_to_usd = AsyncMock(return_value=400.0)
        mock_get_service.return_value = mock_service

        result = await sol_to_usd(2.0)

        assert result == 400.0
        mock_service.sol_to_usd.assert_called_once_with(2.0)


if __name__ == "__main__":
    pytest.main([__file__])

