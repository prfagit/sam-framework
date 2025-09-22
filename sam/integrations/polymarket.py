"""Polymarket Gamma API integration for discovery and opportunity scanning."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from ..core.tools import Tool, ToolSpec
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)

_POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"


class PolymarketIntegrationError(RuntimeError):
    """Raised for Polymarket integration failures."""


@dataclass
class MarketOutcome:
    name: str
    price: float

    @property
    def implied_prob(self) -> float:
        return self.price

    @property
    def net_payout(self) -> float:
        return max(0.0, 1.0 - self.price)

    @property
    def roi(self) -> Optional[float]:
        if self.price <= 0:
            return None
        return (1.0 / self.price) - 1.0


@dataclass
class MarketSnapshot:
    id: str
    question: str
    slug: Optional[str]
    category: Optional[str]
    end_date: Optional[str]
    outcomes: List[MarketOutcome]
    volume_24h: float
    volume_total: float
    liquidity: float
    best_bid: Optional[float]
    best_ask: Optional[float]
    updated_at: Optional[str]
    url: Optional[str]

    @property
    def most_liquid_outcome(self) -> Optional[MarketOutcome]:
        if not self.outcomes:
            return None
        return min(self.outcomes, key=lambda o: o.price if o.price is not None else 1.0)


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_optional_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        # Normalize to ISO 8601 with Z
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(microsecond=0).isoformat()
    except Exception:
        return value


def _parse_outcomes(raw: Dict[str, Any]) -> List[MarketOutcome]:
    raw_outcomes = raw.get("outcomes") or []
    raw_prices = raw.get("outcomePrices") or []

    if isinstance(raw_outcomes, str):
        try:
            raw_outcomes = json.loads(raw_outcomes)
        except json.JSONDecodeError:
            raw_outcomes = []

    if isinstance(raw_prices, str):
        try:
            raw_prices = json.loads(raw_prices)
        except json.JSONDecodeError:
            raw_prices = []

    outcomes: List[MarketOutcome] = []
    for name, price in zip(raw_outcomes, raw_prices):
        try:
            outcomes.append(MarketOutcome(str(name), float(price)))
        except (TypeError, ValueError):
            continue
    return outcomes


class PolymarketGammaClient:
    """Minimal async client for Polymarket Gamma REST endpoints."""

    def __init__(self, base_url: str = _POLYMARKET_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> List[MarketSnapshot]:
        session = await get_session()
        query = dict(params or {})
        url = f"{self.base_url}/markets"

        async with session.get(url, params=self._encode_params(query)) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("Polymarket markets request failed: %s - %s", response.status, text)
                raise PolymarketIntegrationError(
                    f"Polymarket markets request failed with status {response.status}"
                )
            data = await response.json()

        if not isinstance(data, list):
            raise PolymarketIntegrationError("Unexpected response payload for markets endpoint")

        snapshots: List[MarketSnapshot] = []
        for entry in data:
            try:
                snapshots.append(self._normalize_market(entry))
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to normalize market entry %s: %s", entry, exc)
                continue
        return snapshots

    async def fetch_market(self, market_id: str) -> MarketSnapshot:
        session = await get_session()
        url = f"{self.base_url}/markets/{market_id}"
        async with session.get(url) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("Polymarket market detail failed: %s - %s", response.status, text)
                raise PolymarketIntegrationError(
                    f"Polymarket market {market_id} request failed with status {response.status}"
                )
            data = await response.json()

        if not isinstance(data, dict):
            raise PolymarketIntegrationError("Unexpected market detail payload")

        return self._normalize_market(data)

    def _normalize_market(self, raw: Dict[str, Any]) -> MarketSnapshot:
        outcomes = _parse_outcomes(raw)
        slug = raw.get("slug")
        url = f"https://polymarket.com/market/{slug}" if slug else None
        return MarketSnapshot(
            id=str(raw.get("id")),
            question=raw.get("question", ""),
            slug=slug,
            category=raw.get("category"),
            end_date=_parse_iso(raw.get("endDate")),
            outcomes=outcomes,
            volume_24h=_safe_float(raw.get("volume24hr")),
            volume_total=_safe_float(raw.get("volume")),
            liquidity=_safe_float(raw.get("liquidity")),
            best_bid=_safe_optional_float(raw.get("bestBid")),
            best_ask=_safe_optional_float(raw.get("bestAsk")),
            updated_at=_parse_iso(raw.get("updatedAt")),
            url=url,
        )

    @staticmethod
    def _encode_params(params: Dict[str, Any]) -> Dict[str, Any]:
        encoded: Dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                encoded[key] = "true" if value else "false"
            else:
                encoded[key] = value
        return encoded


class MarketListInput(BaseModel):
    limit: int = Field(25, ge=1, le=200, description="Number of markets to fetch")
    offset: int = Field(0, ge=0, description="Offset for pagination")
    active_only: bool = Field(True, description="Return only active, unclosed markets")
    category: Optional[str] = Field(
        None, description="Filter by Polymarket category slug (e.g. 'politics', 'sports')"
    )
    search: Optional[str] = Field(None, description="Search keyword across market questions")
    tag: Optional[str] = Field(None, description="Filter by tag slug")
    series_slug: Optional[str] = Field(None, description="Filter by series slug")


class OpportunityScanInput(BaseModel):
    limit: int = Field(5, ge=1, le=20, description="Number of highlighted opportunities to return")
    universe_limit: int = Field(
        100,
        ge=10,
        le=400,
        description="How many markets to analyze before ranking opportunities",
    )
    min_volume_24h: float = Field(
        500.0,
        ge=0.0,
        description="Minimum 24h traded volume (USDC) required for a market to be considered",
    )
    min_liquidity: float = Field(
        200.0,
        ge=0.0,
        description="Minimum liquidity required for consideration",
    )
    max_entry_price: float = Field(
        0.6,
        gt=0.0,
        le=0.99,
        description="Maximum entry price (share cost) for long ideas",
    )
    category: Optional[str] = Field(
        None, description="Optional category filter (e.g. 'politics', 'sports')"
    )
    tag: Optional[str] = Field(None, description="Optional tag slug filter")

    @field_validator("max_entry_price")
    @classmethod
    def _validate_entry_price(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("max_entry_price must be positive")
        if value >= 1:
            raise ValueError("max_entry_price must be less than 1")
        return value


class StrategyBriefInput(BaseModel):
    count: int = Field(3, ge=1, le=10, description="Number of strategy ideas to return")
    universe_limit: int = Field(
        120,
        ge=20,
        le=500,
        description="Number of markets to scan before crafting strategies",
    )
    min_volume_24h: float = Field(1000.0, ge=0.0)
    min_liquidity: float = Field(400.0, ge=0.0)
    max_entry_price: float = Field(0.65, gt=0.0, lt=1.0)
    category: Optional[str] = Field(None)
    tag: Optional[str] = Field(None)

    @field_validator("max_entry_price")
    @classmethod
    def _validate_strategy_entry(cls, value: float) -> float:
        if not 0.0 < value < 1.0:
            raise ValueError("max_entry_price must be between 0 and 1")
        return value


class PolymarketTools:
    """Tool collection for Polymarket discovery and heuristics."""

    def __init__(self, client: Optional[PolymarketGammaClient] = None) -> None:
        self.client = client or PolymarketGammaClient()
        logger.info("Initialized Polymarket Gamma client")

    async def list_markets(self, args: Dict[str, Any]) -> Dict[str, Any]:
        params = MarketListInput(**args)
        query: Dict[str, Any] = {
            "limit": params.limit,
            "offset": params.offset,
            "active": params.active_only,
            "closed": not params.active_only,
            "archived": False,
        }
        if params.category:
            query["category"] = params.category
        if params.search:
            query["search"] = params.search
        if params.tag:
            query["tags"] = params.tag
        if params.series_slug:
            query["seriesSlug"] = params.series_slug

        markets = await self.client.fetch_markets(query)
        summaries = [self._market_summary(market) for market in markets]
        return {
            "count": len(summaries),
            "results": summaries,
            "note": "Data sourced from Polymarket Gamma API",
        }

    async def scan_opportunities(self, args: Dict[str, Any]) -> Dict[str, Any]:
        params = OpportunityScanInput(**args)
        query: Dict[str, Any] = {
            "limit": params.universe_limit,
            "offset": 0,
            "active": True,
            "closed": False,
            "archived": False,
        }
        if params.category:
            query["category"] = params.category
        if params.tag:
            query["tags"] = params.tag

        universe = await self.client.fetch_markets(query)
        ideas = self._rank_opportunities(
            universe,
            limit=params.limit,
            min_volume=params.min_volume_24h,
            min_liquidity=params.min_liquidity,
            max_entry_price=params.max_entry_price,
        )
        return {
            "opportunities": ideas,
            "scanned_markets": len(universe),
            "parameters": {
                "min_volume_24h": params.min_volume_24h,
                "min_liquidity": params.min_liquidity,
                "max_entry_price": params.max_entry_price,
                "category": params.category,
                "tag": params.tag,
            },
            "disclaimer": (
                "Heuristic ranking only. Any trade involves risk; verify details directly on Polymarket."
            ),
        }

    async def strategy_brief(self, args: Dict[str, Any]) -> Dict[str, Any]:
        params = StrategyBriefInput(**args)
        query: Dict[str, Any] = {
            "limit": params.universe_limit,
            "offset": 0,
            "active": True,
            "closed": False,
            "archived": False,
        }
        if params.category:
            query["category"] = params.category
        if params.tag:
            query["tags"] = params.tag

        universe = await self.client.fetch_markets(query)
        ranked = self._rank_opportunities(
            universe,
            limit=params.count,
            min_volume=params.min_volume_24h,
            min_liquidity=params.min_liquidity,
            max_entry_price=params.max_entry_price,
        )

        strategies = [self._craft_strategy_view(idea) for idea in ranked]
        return {
            "strategies": strategies,
            "scanned_markets": len(universe),
            "note": "Generated heuristics only. Confirm liquidity, spreads, and counterparty risk before trading.",
        }

    def _market_summary(self, market: MarketSnapshot) -> Dict[str, Any]:
        outcomes = [
            {
                "outcome": outcome.name,
                "price": round(outcome.price, 4),
                "implied_probability": round(outcome.implied_prob, 4),
                "net_payout_if_win": round(outcome.net_payout, 4),
            }
            for outcome in market.outcomes
        ]
        return {
            "market_id": market.id,
            "question": market.question,
            "category": market.category,
            "end_date": market.end_date,
            "volume_24h": round(market.volume_24h, 2),
            "liquidity": round(market.liquidity, 2),
            "best_bid": market.best_bid,
            "best_ask": market.best_ask,
            "url": market.url,
            "outcomes": outcomes,
        }

    def _rank_opportunities(
        self,
        universe: List[MarketSnapshot],
        *,
        limit: int,
        min_volume: float,
        min_liquidity: float,
        max_entry_price: float,
    ) -> List[Dict[str, Any]]:
        ranked: List[Tuple[float, Dict[str, Any]]] = []

        for market in universe:
            if market.volume_24h < min_volume:
                continue
            if market.liquidity < min_liquidity:
                continue
            for outcome in market.outcomes:
                if outcome.price <= 0 or outcome.price > max_entry_price:
                    continue
                roi = outcome.roi
                if roi is None or roi <= 0:
                    continue
                volume_component = math.log1p(market.volume_24h)
                liquidity_component = math.log1p(market.liquidity)
                spread_component = 0.0
                if market.best_bid is not None and market.best_ask is not None:
                    spread = max(0.0, market.best_ask - market.best_bid)
                    spread_component = max(0.0, 0.05 - spread)

                score = (
                    roi * (1.0 + volume_component + 0.5 * liquidity_component)
                ) + spread_component
                ranked.append(
                    (
                        score,
                        {
                            "market_id": market.id,
                            "question": market.question,
                            "outcome": outcome.name,
                            "entry_price": round(outcome.price, 4),
                            "implied_probability": round(outcome.implied_prob, 4),
                            "net_payout_if_win": round(outcome.net_payout, 4),
                            "roi_if_win": round(roi, 2),
                            "volume_24h": round(market.volume_24h, 2),
                            "liquidity": round(market.liquidity, 2),
                            "best_bid": market.best_bid,
                            "best_ask": market.best_ask,
                            "market_url": market.url,
                            "ends_at": market.end_date,
                            "score": round(score, 4),
                        },
                    )
                )

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [idea for _, idea in ranked[:limit]]

    def _craft_strategy_view(self, idea: Dict[str, Any]) -> Dict[str, Any]:
        entry_price = idea["entry_price"]
        take_profit = min(0.99, round(entry_price + 0.25, 3))
        stop_loss = max(0.05, round(entry_price - 0.15, 3))

        if entry_price > 0.55:
            take_profit = min(0.95, round(entry_price + 0.18, 3))
            stop_loss = max(0.1, round(entry_price - 0.12, 3))

        risk_reward = round((take_profit - entry_price) / max(0.01, entry_price - stop_loss), 2)

        guidance = (
            "Enter with a limit order between current best bid/ask. Scale out once price clears the take-profit trigger, "
            "and re-evaluate if new data shifts the market narrative."
        )

        return {
            "market_id": idea["market_id"],
            "question": idea["question"],
            "outcome": idea["outcome"],
            "entry_price": entry_price,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "risk_reward_ratio": risk_reward,
            "implied_probability": idea["implied_probability"],
            "volume_24h": idea["volume_24h"],
            "liquidity": idea["liquidity"],
            "market_url": idea["market_url"],
            "ends_at": idea["ends_at"],
            "notes": guidance,
        }


def create_polymarket_tools(polymarket_tools: PolymarketTools) -> List[Tool]:
    async def handle_market_list(args: Dict[str, Any]) -> Dict[str, Any]:
        return await polymarket_tools.list_markets(args)

    async def handle_opportunity_scan(args: Dict[str, Any]) -> Dict[str, Any]:
        return await polymarket_tools.scan_opportunities(args)

    async def handle_strategy_brief(args: Dict[str, Any]) -> Dict[str, Any]:
        return await polymarket_tools.strategy_brief(args)

    return [
        Tool(
            spec=ToolSpec(
                name="polymarket_list_markets",
                description="Fetch current Polymarket markets with key pricing data",
                namespace="polymarket",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 200,
                            "default": 25,
                            "description": "Number of markets to fetch",
                        },
                        "offset": {
                            "type": "integer",
                            "minimum": 0,
                            "default": 0,
                            "description": "Pagination offset",
                        },
                        "active_only": {
                            "type": "boolean",
                            "default": True,
                            "description": "Return only active markets",
                        },
                        "category": {
                            "type": "string",
                            "description": "Filter by category slug (e.g. 'politics')",
                        },
                        "search": {
                            "type": "string",
                            "description": "Keyword search across market questions",
                        },
                        "tag": {
                            "type": "string",
                            "description": "Filter by tag slug",
                        },
                        "series_slug": {
                            "type": "string",
                            "description": "Filter by series slug",
                        },
                    },
                },
            ),
            handler=handle_market_list,
            input_model=MarketListInput,
        ),
        Tool(
            spec=ToolSpec(
                name="polymarket_opportunity_scan",
                description="Analyze Polymarket order book for high-ROI heuristics",
                namespace="polymarket",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                            "description": "Number of highlighted ideas to return",
                        },
                        "universe_limit": {
                            "type": "integer",
                            "minimum": 10,
                            "maximum": 400,
                            "default": 100,
                            "description": "Number of markets to scan before ranking",
                        },
                        "min_volume_24h": {
                            "type": "number",
                            "minimum": 0,
                            "default": 500,
                            "description": "Minimum 24h volume required",
                        },
                        "min_liquidity": {
                            "type": "number",
                            "minimum": 0,
                            "default": 200,
                            "description": "Minimum liquidity required",
                        },
                        "max_entry_price": {
                            "type": "number",
                            "minimum": 0.01,
                            "maximum": 0.99,
                            "default": 0.6,
                            "description": "Maximum entry price for long exposure",
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional category filter",
                        },
                        "tag": {
                            "type": "string",
                            "description": "Optional tag filter",
                        },
                    },
                },
            ),
            handler=handle_opportunity_scan,
            input_model=OpportunityScanInput,
        ),
        Tool(
            spec=ToolSpec(
                name="polymarket_strategy_brief",
                description="Generate Polymarket trade ideas with suggested entries, exits, and risk framing",
                namespace="polymarket",
                input_schema={
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 3,
                        },
                        "universe_limit": {
                            "type": "integer",
                            "minimum": 20,
                            "maximum": 500,
                            "default": 120,
                        },
                        "min_volume_24h": {
                            "type": "number",
                            "minimum": 0,
                            "default": 1000,
                        },
                        "min_liquidity": {
                            "type": "number",
                            "minimum": 0,
                            "default": 400,
                        },
                        "max_entry_price": {
                            "type": "number",
                            "minimum": 0.01,
                            "maximum": 0.99,
                            "default": 0.65,
                        },
                        "category": {"type": "string"},
                        "tag": {"type": "string"},
                    },
                },
            ),
            handler=handle_strategy_brief,
            input_model=StrategyBriefInput,
        ),
    ]
