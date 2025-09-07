from dexscreener import DexscreenerClient
import logging
import asyncio
from typing import Dict, Any, List

from ..core.tools import Tool, ToolSpec
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DexScreenerTools:
    def __init__(self):
        self.client = DexscreenerClient()
        logger.info("Initialized DexScreener client")

    async def search_pairs(self, query: str) -> Dict[str, Any]:
        """Search for trading pairs by query."""
        try:
            # Run synchronous client in thread to avoid blocking event loop
            results = await asyncio.to_thread(self.client.search_pairs, query)

            # DexScreener client returns a list of TokenPair objects
            if not isinstance(results, list):
                logger.error(f"Expected list but got {type(results)}: {results}")
                return {"error": "API returned unexpected format"}

            pairs = []
            for pair in results:  # results is already a list
                pairs.append(
                    {
                        "chain_id": pair.chain_id,
                        "dex_id": pair.dex_id,
                        "pair_address": pair.pair_address,
                        "base_token": {
                            "address": pair.base_token.address,
                            "name": pair.base_token.name,
                            "symbol": pair.base_token.symbol,
                        },
                        "quote_token": {
                            "address": pair.quote_token.address,
                            "name": pair.quote_token.name,
                            "symbol": pair.quote_token.symbol,
                        },
                        "price_usd": pair.price_usd,
                        "price_change_24h": pair.price_change.h24 if pair.price_change else None,
                        "volume_24h": pair.volume.h24 if pair.volume else None,
                        "liquidity": pair.liquidity.usd if pair.liquidity else None,
                        "market_cap": getattr(pair, "market_cap", None),
                        "created_at": pair.pair_created_at,
                    }
                )

            logger.info(f"Found {len(pairs)} pairs for query: {query}")
            return {"query": query, "pairs": pairs, "total_pairs": len(pairs)}

        except Exception as e:
            logger.error(f"Error searching pairs: {e}")
            return {"error": str(e)}

    async def get_token_pairs(self, token_address: str) -> Dict[str, Any]:
        """Get all trading pairs for a specific token."""
        try:
            # Run synchronous client in thread to avoid blocking event loop
            results = await asyncio.to_thread(self.client.get_token_pairs, token_address)

            # DexScreener client returns a list of TokenPair objects
            if not isinstance(results, list):
                logger.error(f"Expected list but got {type(results)}: {results}")
                return {"error": "API returned unexpected format"}

            pairs = []
            for pair in results:  # results is already a list
                pairs.append(
                    {
                        "chain_id": pair.chain_id,
                        "dex_id": pair.dex_id,
                        "pair_address": pair.pair_address,
                        "base_token": {
                            "address": pair.base_token.address,
                            "name": pair.base_token.name,
                            "symbol": pair.base_token.symbol,
                        },
                        "quote_token": {
                            "address": pair.quote_token.address,
                            "name": pair.quote_token.name,
                            "symbol": pair.quote_token.symbol,
                        },
                        "price_usd": pair.price_usd,
                        "price_change_24h": pair.price_change.h24 if pair.price_change else None,
                        "volume_24h": pair.volume.h24 if pair.volume else None,
                        "liquidity": pair.liquidity.usd if pair.liquidity else None,
                        "fdv": getattr(pair, "fdv", None),
                        "market_cap": getattr(pair, "market_cap", None),
                    }
                )

            logger.info(f"Found {len(pairs)} pairs for token: {token_address}")
            return {"token_address": token_address, "pairs": pairs, "total_pairs": len(pairs)}

        except Exception as e:
            logger.error(f"Error getting token pairs: {e}")
            return {"error": str(e)}

    async def get_solana_pair(self, pair_address: str) -> Dict[str, Any]:
        """Get detailed information for a specific Solana pair."""
        try:
            # Run synchronous client in thread to avoid blocking event loop
            results = await asyncio.to_thread(self.client.get_token_pairs, f"solana:{pair_address}")

            if not results:
                return {"error": "Pair not found"}

            # results might be a TokenPair object directly or a dict with "pair"
            if hasattr(results, "chain_id"):
                # It's a TokenPair object
                pair = results
            elif isinstance(results, dict) and "pair" in results:
                # It's a dict with pair data
                pair = results["pair"]
            else:
                return {"error": "Unexpected response format"}

            # Handle both TokenPair objects and dicts
            if hasattr(pair, "chain_id"):
                # TokenPair object
                pair_info = {
                    "chain_id": pair.chain_id,
                    "dex_id": pair.dex_id,
                    "pair_address": pair.pair_address,
                    "base_token": {
                        "address": pair.base_token.address,
                        "name": pair.base_token.name,
                        "symbol": pair.base_token.symbol,
                    },
                    "quote_token": {
                        "address": pair.quote_token.address,
                        "name": pair.quote_token.name,
                        "symbol": pair.quote_token.symbol,
                    },
                    "price_usd": pair.price_usd,
                    "price_change": {
                        "1h": pair.price_change.h1 if pair.price_change else None,
                        "6h": pair.price_change.h6 if pair.price_change else None,
                        "24h": pair.price_change.h24 if pair.price_change else None,
                    },
                    "volume": {
                        "1h": pair.volume.h1 if pair.volume else None,
                        "6h": pair.volume.h6 if pair.volume else None,
                        "24h": pair.volume.h24 if pair.volume else None,
                    },
                    "liquidity": pair.liquidity.usd if pair.liquidity else None,
                    "fdv": pair.fdv,
                    "market_cap": getattr(pair, "market_cap", None),
                    "created_at": pair.pair_created_at,
                    "url": pair.url,
                    "info": getattr(pair, "info", None),
                }
            else:
                # Dict format (fallback)
                pair_info = {
                    "chain_id": pair.get("chainId"),
                    "dex_id": pair.get("dexId"),
                    "pair_address": pair.get("pairAddress"),
                    "base_token": {
                        "address": pair.get("baseToken", {}).get("address"),
                        "name": pair.get("baseToken", {}).get("name"),
                        "symbol": pair.get("baseToken", {}).get("symbol"),
                    },
                    "quote_token": {
                        "address": pair.get("quoteToken", {}).get("address"),
                        "name": pair.get("quoteToken", {}).get("name"),
                        "symbol": pair.get("quoteToken", {}).get("symbol"),
                    },
                    "price_usd": pair.get("priceUsd"),
                    "price_change": {
                        "1h": pair.get("priceChange", {}).get("h1"),
                        "6h": pair.get("priceChange", {}).get("h6"),
                        "24h": pair.get("priceChange", {}).get("h24"),
                    },
                    "volume": {
                        "1h": pair.get("volume", {}).get("h1"),
                        "6h": pair.get("volume", {}).get("h6"),
                        "24h": pair.get("volume", {}).get("h24"),
                    },
                    "liquidity": pair.get("liquidity", {}).get("usd"),
                    "fdv": pair.get("fdv"),
                    "market_cap": pair.get("marketCap"),
                    "created_at": pair.get("pairCreatedAt"),
                    "url": pair.get("url"),
                    "info": pair.get("info"),
                }

            logger.info(f"Retrieved pair info for: {pair_address}")
            return pair_info

        except Exception as e:
            logger.error(f"Error getting Solana pair: {e}")
            return {"error": str(e)}

    async def get_trending_pairs(self, chain: str = "solana") -> Dict[str, Any]:
        """Get trending pairs for a specific chain."""
        try:
            # DexScreener doesn't have a direct trending endpoint,
            # so we'll search for popular tokens and sort by volume
            popular_tokens = ["SOL", "USDC", "USDT"]
            all_pairs = []

            for token in popular_tokens:
                try:
                    results = await asyncio.to_thread(self.client.search_pairs, f"{token} {chain}")
                    if results:  # results is a list of TokenPair objects
                        all_pairs.extend(results[:5])  # Take top 5 for each
                except Exception as e:
                    logger.warning(f"Error getting pairs for {token}: {e}")
                    continue

            # Sort by 24h volume
            sorted_pairs = sorted(
                all_pairs,
                key=lambda x: float(x.volume.h24 if x.volume and x.volume.h24 else 0),
                reverse=True,
            )[:10]  # Top 10

            trending_pairs = []
            for pair in sorted_pairs:
                trending_pairs.append(
                    {
                        "pair_address": pair.pair_address,
                        "base_token": {
                            "address": pair.base_token.address,
                            "name": pair.base_token.name,
                            "symbol": pair.base_token.symbol,
                        },
                        "quote_token": {
                            "address": pair.quote_token.address,
                            "name": pair.quote_token.name,
                            "symbol": pair.quote_token.symbol,
                        },
                        "price_usd": pair.price_usd,
                        "volume_24h": pair.volume.h24 if pair.volume else None,
                        "price_change_24h": pair.price_change.h24 if pair.price_change else None,
                        "liquidity": pair.liquidity.usd if pair.liquidity else None,
                    }
                )

            logger.info(f"Retrieved {len(trending_pairs)} trending pairs for {chain}")
            return {
                "chain": chain,
                "trending_pairs": trending_pairs,
                "total_pairs": len(trending_pairs),
            }

        except Exception as e:
            logger.error(f"Error getting trending pairs: {e}")
            return {"error": str(e)}


def create_dexscreener_tools(dex_tools: DexScreenerTools) -> List[Tool]:
    """Create DexScreener tool instances."""

    class SearchPairsInput(BaseModel):
        query: str = Field(..., description="Search query (token name/symbol/address)")

    class GetTokenPairsInput(BaseModel):
        token_address: str = Field(..., description="Token address")

    class GetSolanaPairInput(BaseModel):
        pair_address: str = Field(..., description="Pair address")

    class GetTrendingPairsInput(BaseModel):
        chain: str = Field("solana", description="Blockchain to list trending pairs")

    async def handle_search_pairs(args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query", "")
        return await dex_tools.search_pairs(query)

    async def handle_get_token_pairs(args: Dict[str, Any]) -> Dict[str, Any]:
        token_address = args.get("token_address", "")
        return await dex_tools.get_token_pairs(token_address)

    async def handle_get_solana_pair(args: Dict[str, Any]) -> Dict[str, Any]:
        pair_address = args.get("pair_address", "")
        return await dex_tools.get_solana_pair(pair_address)

    async def handle_get_trending_pairs(args: Dict[str, Any]) -> Dict[str, Any]:
        chain = args.get("chain", "solana")
        return await dex_tools.get_trending_pairs(chain)

    tools = [
        Tool(
            spec=ToolSpec(
                name="search_pairs",
                description="Search for trading pairs by token name or symbol",
                input_schema={
                    "name": "search_pairs",
                    "description": "Search trading pairs",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (token name, symbol, or address)",
                            }
                        },
                        "required": ["query"],
                    },
                },
            ),
            handler=handle_search_pairs,
            input_model=SearchPairsInput,
        ),
        Tool(
            spec=ToolSpec(
                name="get_token_pairs",
                description="Get all trading pairs for a specific token address",
                input_schema={
                    "name": "get_token_pairs",
                    "description": "Get token trading pairs",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "token_address": {
                                "type": "string",
                                "description": "Token address to get pairs for",
                            }
                        },
                        "required": ["token_address"],
                    },
                },
            ),
            handler=handle_get_token_pairs,
            input_model=GetTokenPairsInput,
        ),
        Tool(
            spec=ToolSpec(
                name="get_solana_pair",
                description="Get detailed information for a specific Solana trading pair",
                input_schema={
                    "name": "get_solana_pair",
                    "description": "Get Solana pair details",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pair_address": {
                                "type": "string",
                                "description": "Pair address to get details for",
                            }
                        },
                        "required": ["pair_address"],
                    },
                },
            ),
            handler=handle_get_solana_pair,
            input_model=GetSolanaPairInput,
        ),
        Tool(
            spec=ToolSpec(
                name="get_trending_pairs",
                description="Get trending trading pairs for a specific blockchain",
                input_schema={
                    "name": "get_trending_pairs",
                    "description": "Get trending trading pairs",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "chain": {
                                "type": "string",
                                "description": "Blockchain to get trending pairs for",
                                "default": "solana",
                            }
                        },
                        "required": [],
                    },
                },
            ),
            handler=handle_get_trending_pairs,
            input_model=GetTrendingPairsInput,
        ),
    ]

    return tools
