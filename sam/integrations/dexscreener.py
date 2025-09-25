from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, TypeGuard, cast

from dexscreener import DexscreenerClient
from pydantic import BaseModel, Field

from ..core.tools import Tool, ToolSpec

logger = logging.getLogger(__name__)


class PriceWindow(Protocol):
    h1: Optional[float]
    h6: Optional[float]
    h24: Optional[float]


class VolumeWindow(Protocol):
    h1: Optional[float]
    h6: Optional[float]
    h24: Optional[float]


class TokenInfo(Protocol):
    address: str
    name: Optional[str]
    symbol: Optional[str]


class LiquidityInfo(Protocol):
    usd: Optional[float]


class TokenPair(Protocol):
    chain_id: Optional[str]
    dex_id: Optional[str]
    pair_address: Optional[str]
    base_token: TokenInfo
    quote_token: TokenInfo
    price_usd: Optional[float]
    price_change: Optional[PriceWindow]
    volume: Optional[VolumeWindow]
    liquidity: Optional[LiquidityInfo]
    fdv: Optional[float]
    market_cap: Optional[float]
    pair_created_at: Optional[int]
    url: Optional[str]
    info: Optional[Dict[str, Any]]


class DexClientProtocol(Protocol):
    def search_pairs(self, query: str) -> Sequence[TokenPair]:
        ...

    def get_token_pairs(self, token: str) -> Sequence[TokenPair]:
        ...

    def get_trending_pairs(self, chain: Optional[str] = None) -> Sequence[TokenPair]:
        ...


PairLike = TokenPair | Mapping[str, Any]


def _is_mapping_pair(pair: PairLike) -> TypeGuard[Mapping[str, Any]]:
    return isinstance(pair, Mapping)


def _is_token_pair(pair: PairLike) -> TypeGuard[TokenPair]:
    return not isinstance(pair, Mapping)


class DexScreenerTools:
    def __init__(self, client: Optional[DexClientProtocol] = None) -> None:
        self.client: DexClientProtocol = cast(DexClientProtocol, client or DexscreenerClient())
        logger.info("Initialized DexScreener client")

    async def search_pairs(self, query: str) -> Dict[str, Any]:
        """Search for trading pairs by query."""
        try:
            # Run synchronous client in thread to avoid blocking event loop
            results = await asyncio.to_thread(self.client.search_pairs, query)

            pairs = [_serialize_pair_summary(pair) for pair in _ensure_sequence(results)]

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

            pairs = [_serialize_pair_summary(pair) for pair in _ensure_sequence(results)]

            logger.info(f"Found {len(pairs)} pairs for token: {token_address}")
            return {"token_address": token_address, "pairs": pairs, "total_pairs": len(pairs)}

        except Exception as e:
            logger.error(f"Error getting token pairs: {e}")
            return {"error": str(e)}

    async def get_solana_pair(self, pair_address: str) -> Dict[str, Any]:
        """Get detailed information for a specific Solana pair."""
        try:
            # Run synchronous client in thread to avoid blocking event loop
            results = await asyncio.to_thread(
                self.client.get_token_pairs, f"solana:{pair_address}"
            )

            pair = _extract_single_pair(results)
            pair_info = _serialize_pair_detail(pair)

            logger.info(f"Retrieved pair info for: {pair_address}")
            return pair_info

        except Exception as e:
            logger.error(f"Error getting Solana pair: {e}")
            return {"error": str(e)}

    async def get_trending_pairs(self, chain: str = "solana") -> Dict[str, Any]:
        """Get trending pairs for a specific chain."""
        try:
            results = await asyncio.to_thread(self.client.get_trending_pairs, chain)
            seq = _ensure_sequence(results)
            trending_pairs = [_serialize_trending_pair(pair) for pair in seq]
            return {
                "chain": chain,
                "trending_pairs": trending_pairs,
                "total_pairs": len(trending_pairs),
            }
        except AttributeError:
            return await self._fallback_trending_pairs(chain)
        except Exception as e:  # pragma: no cover - client/runtime errors
            logger.error(f"Error getting trending pairs: {e}")
            return {"error": str(e)}

    async def _fallback_trending_pairs(self, chain: str) -> Dict[str, Any]:
        """Fallback trending computation using search + heuristics."""
        popular_tokens = ["SOL", "USDC", "USDT"]
        all_pairs: List[PairLike] = []

        for token in popular_tokens:
            try:
                results = await asyncio.to_thread(
                    self.client.search_pairs, f"{token} {chain}"
                )
                all_pairs.extend(_ensure_sequence(results)[:5])
            except Exception as e:
                logger.warning(f"Error getting pairs for {token}: {e}")
                continue

        sorted_pairs = sorted(all_pairs, key=_volume_24h, reverse=True)[:10]
        trending_pairs = [_serialize_trending_pair(pair) for pair in sorted_pairs]

        logger.info(f"Retrieved {len(trending_pairs)} fallback trending pairs for {chain}")
        return {
            "chain": chain,
            "trending_pairs": trending_pairs,
            "total_pairs": len(trending_pairs),
        }


def _ensure_sequence(results: Any) -> Sequence[PairLike]:
    if isinstance(results, Sequence) and not isinstance(results, (str, bytes)):
        return cast(Sequence[PairLike], results)
    logger.error(f"Expected sequence of TokenPair, got {type(results)}: {results}")
    return []


def _serialize_token(token: TokenInfo) -> Dict[str, Optional[str]]:
    return {
        "address": token.address,
        "name": token.name,
        "symbol": token.symbol,
    }


def _serialize_token_mapping(data: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "address": cast(Optional[str], data.get("address")),
        "name": cast(Optional[str], data.get("name")),
        "symbol": cast(Optional[str], data.get("symbol")),
    }


def _serialize_pair_summary(pair: PairLike) -> Dict[str, Any]:
    if _is_mapping_pair(pair):
        base = cast(Mapping[str, Any], pair.get("baseToken", {}))
        quote = cast(Mapping[str, Any], pair.get("quoteToken", {}))
        price_change_data = cast(Mapping[str, Any], pair.get("priceChange", {}))
        volume_data = cast(Mapping[str, Any], pair.get("volume", {}))
        liquidity_data = cast(Mapping[str, Any], pair.get("liquidity", {}))
        return {
            "chain_id": pair.get("chainId"),
            "dex_id": pair.get("dexId"),
            "pair_address": pair.get("pairAddress"),
            "base_token": _serialize_token_mapping(base),
            "quote_token": _serialize_token_mapping(quote),
            "price_usd": pair.get("priceUsd"),
            "price_change_24h": price_change_data.get("h24"),
            "volume_24h": volume_data.get("h24"),
            "liquidity": liquidity_data.get("usd"),
            "fdv": pair.get("fdv"),
            "market_cap": pair.get("marketCap"),
            "created_at": pair.get("pairCreatedAt"),
        }

    assert _is_token_pair(pair)
    token_pair: TokenPair = pair
    return {
        "chain_id": token_pair.chain_id,
        "dex_id": token_pair.dex_id,
        "pair_address": token_pair.pair_address,
        "base_token": _serialize_token(token_pair.base_token),
        "quote_token": _serialize_token(token_pair.quote_token),
        "price_usd": token_pair.price_usd,
        "price_change_24h": token_pair.price_change.h24
        if token_pair.price_change
        else None,
        "volume_24h": token_pair.volume.h24 if token_pair.volume else None,
        "liquidity": token_pair.liquidity.usd if token_pair.liquidity else None,
        "fdv": token_pair.fdv,
        "market_cap": token_pair.market_cap,
        "created_at": token_pair.pair_created_at,
    }

def _extract_single_pair(results: Any) -> PairLike:
    if isinstance(results, Sequence) and results and not isinstance(results, (str, bytes)):
        return cast(PairLike, results[0])
    if isinstance(results, Mapping) and "pair" in results:
        return cast(PairLike, results["pair"])
    if hasattr(results, "chain_id"):
        return cast(TokenPair, results)
    raise ValueError("Unexpected response format from DexScreener")


def _serialize_pair_detail(pair: PairLike) -> Dict[str, Any]:
    if _is_mapping_pair(pair):
        data = pair
        base = cast(Mapping[str, Any], data.get("baseToken", {}))
        quote = cast(Mapping[str, Any], data.get("quoteToken", {}))
        price_change_data = cast(Mapping[str, Any], data.get("priceChange", {}))
        volume_data = cast(Mapping[str, Any], data.get("volume", {}))
        liquidity_data = cast(Mapping[str, Any], data.get("liquidity", {}))
        return {
            "chain_id": data.get("chainId"),
            "dex_id": data.get("dexId"),
            "pair_address": data.get("pairAddress"),
            "base_token": _serialize_token_mapping(base),
            "quote_token": _serialize_token_mapping(quote),
            "price_usd": data.get("priceUsd"),
            "price_change": {
                "1h": price_change_data.get("h1"),
                "6h": price_change_data.get("h6"),
                "24h": price_change_data.get("h24"),
            },
            "volume": {
                "1h": volume_data.get("h1"),
                "6h": volume_data.get("h6"),
                "24h": volume_data.get("h24"),
            },
            "liquidity": liquidity_data.get("usd"),
            "fdv": data.get("fdv"),
            "market_cap": data.get("marketCap"),
            "created_at": data.get("pairCreatedAt"),
            "url": data.get("url"),
            "info": data.get("info"),
        }

    assert _is_token_pair(pair)
    token_pair: TokenPair = pair
    price_window = token_pair.price_change
    volume_window = token_pair.volume
    return {
        "chain_id": token_pair.chain_id,
        "dex_id": token_pair.dex_id,
        "pair_address": token_pair.pair_address,
        "base_token": _serialize_token(token_pair.base_token),
        "quote_token": _serialize_token(token_pair.quote_token),
        "price_usd": token_pair.price_usd,
        "price_change": {
            "1h": price_window.h1 if price_window else None,
            "6h": price_window.h6 if price_window else None,
            "24h": price_window.h24 if price_window else None,
        },
        "volume": {
            "1h": volume_window.h1 if volume_window else None,
            "6h": volume_window.h6 if volume_window else None,
            "24h": volume_window.h24 if volume_window else None,
        },
        "liquidity": token_pair.liquidity.usd if token_pair.liquidity else None,
        "fdv": token_pair.fdv,
        "market_cap": token_pair.market_cap,
        "created_at": token_pair.pair_created_at,
        "url": token_pair.url,
        "info": token_pair.info,
    }


def _volume_24h(pair: PairLike) -> float:
    if _is_mapping_pair(pair):
        volume = pair.get("volume", {})
        value = None
        if isinstance(volume, Mapping):
            value = volume.get("h24")
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    assert _is_token_pair(pair)
    token_pair: TokenPair = pair
    vol = token_pair.volume
    return float(vol.h24) if vol and vol.h24 is not None else 0.0


def _serialize_trending_pair(pair: PairLike) -> Dict[str, Any]:
    summary = _serialize_pair_summary(pair)
    return {
        "pair_address": summary.get("pair_address"),
        "base_token": summary.get("base_token"),
        "quote_token": summary.get("quote_token"),
        "price_usd": summary.get("price_usd"),
        "volume_24h": summary.get("volume_24h"),
        "price_change_24h": summary.get("price_change_24h"),
        "liquidity": summary.get("liquidity"),
    }


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
