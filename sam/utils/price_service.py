"""Price service for USD conversions using Jupiter API."""

import asyncio
import logging
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass
from .http_client import get_session

logger = logging.getLogger(__name__)


@dataclass
class PriceData:
    """Price information with caching metadata."""
    price_usd: float
    timestamp: float
    source: str = "jupiter"
    
    @property
    def is_stale(self, ttl_seconds: int = 30) -> bool:
        """Check if price data is stale."""
        return time.time() - self.timestamp > ttl_seconds
    
    @property
    def age_seconds(self) -> float:
        """Get age of price data in seconds."""
        return time.time() - self.timestamp


class PriceService:
    """Service for fetching and caching cryptocurrency prices."""
    
    def __init__(self, cache_ttl: int = 30):
        self.cache_ttl = cache_ttl  # Cache for 30 seconds
        self._price_cache: Dict[str, PriceData] = {}
        self._lock = asyncio.Lock()
        
        # Common token mint addresses for quick reference
        self.COMMON_TOKENS = {
            "SOL": "So11111111111111111111111111111111111111112",
            "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
        }
    
    async def get_sol_price_usd(self) -> float:
        """Get current SOL price in USD from Jupiter."""
        try:
            async with self._lock:
                # Check cache first
                cached_sol = self._price_cache.get("SOL")
                if cached_sol and not cached_sol.is_stale(self.cache_ttl):
                    logger.debug(f"Using cached SOL price: ${cached_sol.price_usd} (age: {cached_sol.age_seconds:.1f}s)")
                    return cached_sol.price_usd
                
                # Fetch fresh price from Jupiter
                session = await get_session()
                
                # Jupiter price API endpoint
                url = "https://price.jup.ag/v4/price"
                params = {"ids": "SOL"}
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if "data" in data and "SOL" in data["data"]:
                            price_usd = float(data["data"]["SOL"]["price"])
                            
                            # Cache the result
                            self._price_cache["SOL"] = PriceData(
                                price_usd=price_usd,
                                timestamp=time.time(),
                                source="jupiter"
                            )
                            
                            logger.debug(f"Fetched fresh SOL price: ${price_usd}")
                            return price_usd
                        else:
                            logger.warning("SOL price not found in Jupiter response")
                            return await self._get_fallback_sol_price()
                    else:
                        logger.warning(f"Jupiter price API error: {response.status}")
                        return await self._get_fallback_sol_price()
        
        except Exception as e:
            logger.error(f"Error fetching SOL price: {e}")
            return await self._get_fallback_sol_price()
    
    async def _get_fallback_sol_price(self) -> float:
        """Fallback to cached price or estimated price."""
        # Try to use stale cached price
        cached_sol = self._price_cache.get("SOL")
        if cached_sol:
            logger.info(f"Using stale cached SOL price: ${cached_sol.price_usd} (age: {cached_sol.age_seconds:.1f}s)")
            return cached_sol.price_usd
        
        # Last resort: use a reasonable estimate
        estimated_price = 150.0  # Conservative estimate
        logger.warning(f"Using estimated SOL price: ${estimated_price}")
        return estimated_price
    
    async def sol_to_usd(self, sol_amount: float) -> float:
        """Convert SOL amount to USD."""
        sol_price = await self.get_sol_price_usd()
        return sol_amount * sol_price
    
    async def format_sol_with_usd(self, sol_amount: float) -> str:
        """Format SOL amount with USD equivalent."""
        if sol_amount == 0:
            return "0 SOL ($0.00)"
        
        try:
            usd_value = await self.sol_to_usd(sol_amount)
            
            # Smart formatting based on amounts
            if sol_amount >= 1:
                sol_str = f"{sol_amount:.3f}"
            elif sol_amount >= 0.001:
                sol_str = f"{sol_amount:.4f}"
            else:
                sol_str = f"{sol_amount:.6f}"
            
            if usd_value >= 1:
                usd_str = f"${usd_value:.2f}"
            elif usd_value >= 0.01:
                usd_str = f"${usd_value:.3f}"
            else:
                usd_str = f"${usd_value:.4f}"
            
            return f"{sol_str} SOL ({usd_str})"
        
        except Exception as e:
            logger.error(f"Error formatting SOL with USD: {e}")
            return f"{sol_amount:.4f} SOL"
    
    async def format_portfolio_value(self, sol_balance: float, tokens: list = None) -> Dict[str, Any]:
        """Format complete portfolio with USD values."""
        try:
            sol_usd = await self.sol_to_usd(sol_balance)
            
            # For now, we'll just show SOL value
            # In the future, we could add token USD values too
            total_usd = sol_usd
            
            return {
                "sol_balance": sol_balance,
                "sol_usd": sol_usd,
                "total_usd": total_usd,
                "formatted_sol": await self.format_sol_with_usd(sol_balance),
                "formatted_total": f"${total_usd:.2f}",
                "sol_price": await self.get_sol_price_usd()
            }
        
        except Exception as e:
            logger.error(f"Error formatting portfolio: {e}")
            return {
                "sol_balance": sol_balance,
                "sol_usd": 0.0,
                "total_usd": 0.0,
                "formatted_sol": f"{sol_balance:.4f} SOL",
                "formatted_total": "$0.00",
                "sol_price": 0.0
            }
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for debugging."""
        stats = {
            "cached_tokens": len(self._price_cache),
            "cache_ttl": self.cache_ttl,
            "tokens": {}
        }
        
        for token, price_data in self._price_cache.items():
            stats["tokens"][token] = {
                "price_usd": price_data.price_usd,
                "age_seconds": price_data.age_seconds,
                "is_stale": price_data.is_stale(self.cache_ttl),
                "source": price_data.source
            }
        
        return stats
    
    async def clear_cache(self):
        """Clear all cached prices."""
        async with self._lock:
            self._price_cache.clear()
            logger.info("Price cache cleared")


# Global price service instance
_global_price_service: Optional[PriceService] = None
_price_service_lock = asyncio.Lock()


async def get_price_service() -> PriceService:
    """Get global price service instance."""
    global _global_price_service
    
    if _global_price_service is None:
        async with _price_service_lock:
            if _global_price_service is None:
                _global_price_service = PriceService()
    
    return _global_price_service


async def cleanup_price_service():
    """Cleanup global price service."""
    global _global_price_service
    if _global_price_service:
        await _global_price_service.clear_cache()
        _global_price_service = None


# Convenience functions
async def get_sol_price() -> float:
    """Get current SOL price in USD."""
    service = await get_price_service()
    return await service.get_sol_price_usd()


async def format_sol_usd(sol_amount: float) -> str:
    """Format SOL amount with USD value."""
    service = await get_price_service()
    return await service.format_sol_with_usd(sol_amount)


async def sol_to_usd(sol_amount: float) -> float:
    """Convert SOL to USD."""
    service = await get_price_service()
    return await service.sol_to_usd(sol_amount)