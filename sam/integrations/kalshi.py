"""Kalshi API integration for prediction market discovery and trading.

Supports both public (unauthenticated) and private (authenticated) endpoints.
Authentication uses RSA-PSS signatures as per Kalshi API specification.
"""

from __future__ import annotations

import base64
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, Field, field_validator

from ..config.settings import Settings
from ..core.tools import Tool, ToolSpec
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)


class KalshiIntegrationError(RuntimeError):
    """Raised when Kalshi API calls fail."""


def _safe_cents_price(value: Any) -> Optional[float]:
    """Convert API price values (in cents) to dollar probability floats."""
    try:
        if value is None:
            return None
        return round(float(value) / 100.0, 4)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _normalize_timestamp(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(microsecond=0).isoformat()
    except Exception:
        return value


@dataclass
class KalshiMarket:
    ticker: str
    title: str
    subtitle: Optional[str]
    event_ticker: Optional[str]
    status: str
    category: Optional[str]
    open_time: Optional[str]
    close_time: Optional[str]
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    last_price: Optional[float]
    volume: Optional[float]
    volume_24h: Optional[float]
    open_interest: Optional[float]
    liquidity: Optional[float]
    url: Optional[str]

    @property
    def entry_price(self) -> Optional[float]:
        if self.yes_ask is not None:
            return self.yes_ask
        if self.last_price is not None:
            return self.last_price
        return self.yes_bid


@dataclass
class KalshiMarketsResponse:
    markets: List[KalshiMarket]
    cursor: Optional[str]


class KalshiAuthenticator:
    """Handles RSA-PSS authentication for Kalshi API requests."""

    def __init__(self, key_id: str, private_key: rsa.RSAPrivateKey) -> None:
        self.key_id = key_id
        self.private_key = private_key

    @classmethod
    def from_file(cls, key_id: str, private_key_path: str) -> KalshiAuthenticator:
        """Load private key from PEM file."""
        path = Path(private_key_path).expanduser()
        if not path.exists():
            raise KalshiIntegrationError(f"Private key file not found: {private_key_path}")

        with open(path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(), password=None, backend=default_backend()
            )

        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise KalshiIntegrationError("Invalid RSA private key format")

        return cls(key_id, private_key)

    def sign_request(self, method: str, path: str) -> Dict[str, str]:
        """Generate authentication headers for a request.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path WITHOUT query parameters

        Returns:
            Dictionary with KALSHI-ACCESS-* headers
        """
        # Generate timestamp in milliseconds
        timestamp_ms = int(time.time() * 1000)
        timestamp_str = str(timestamp_ms)

        # Strip query parameters from path before signing (per Kalshi docs)
        path_without_query = path.split("?")[0]

        # Create signature message: timestamp + method + path
        message = f"{timestamp_str}{method}{path_without_query}"

        # Sign with RSA-PSS
        signature = self._sign_pss_text(message)

        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
        }

    def _sign_pss_text(self, text: str) -> str:
        """Sign text using RSA-PSS with SHA256."""
        message = text.encode("utf-8")
        try:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256(),
            )
            return base64.b64encode(signature).decode("utf-8")
        except InvalidSignature as e:
            raise KalshiIntegrationError("RSA signature failed") from e


class KalshiClient:
    """Async client for Kalshi REST API with optional authentication."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        market_url_base: Optional[str] = None,
        authenticator: Optional[KalshiAuthenticator] = None,
    ) -> None:
        # Use demo URL if KALSHI_USE_DEMO is True
        if base_url is None:
            base_url = (
                Settings.KALSHI_DEMO_API_BASE_URL
                if Settings.KALSHI_USE_DEMO
                else Settings.KALSHI_API_BASE_URL
            )

        self.base_url = base_url.rstrip("/")
        self.market_url_base = (market_url_base or Settings.KALSHI_MARKET_URL).rstrip("/")
        self.authenticator = authenticator

        mode = "demo" if Settings.KALSHI_USE_DEMO else "production"
        auth_status = "authenticated" if authenticator else "public"
        logger.info(f"Initialized Kalshi client: {mode} mode, {auth_status}")

    @classmethod
    def from_settings(cls) -> KalshiClient:
        """Create client from Settings configuration."""
        authenticator = None
        if Settings.KALSHI_API_KEY_ID and Settings.KALSHI_PRIVATE_KEY_PATH:
            try:
                authenticator = KalshiAuthenticator.from_file(
                    Settings.KALSHI_API_KEY_ID, Settings.KALSHI_PRIVATE_KEY_PATH
                )
                logger.info("Kalshi authentication enabled")
            except Exception as e:
                logger.warning(f"Failed to load Kalshi credentials: {e}")

        return cls(authenticator=authenticator)

    async def get_markets(self, params: Optional[Dict[str, Any]] = None) -> KalshiMarketsResponse:
        """Fetch markets list (public endpoint, no auth required)."""
        session = await get_session()
        query = dict(params or {})
        path = "/markets"
        url = f"{self.base_url}{path}"

        headers = {}
        if self.authenticator:
            # Even though this is a public endpoint, we can still authenticate
            headers.update(self.authenticator.sign_request("GET", path))

        async with session.get(url, params=query, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("Kalshi markets request failed: %s - %s", response.status, text)
                raise KalshiIntegrationError(
                    f"Kalshi markets request failed with status {response.status}: {text}"
                )
            payload = await response.json()

        markets_payload = payload.get("markets") if isinstance(payload, dict) else None
        cursor = payload.get("cursor") if isinstance(payload, dict) else None

        markets: List[KalshiMarket] = []
        if isinstance(markets_payload, Iterable):
            for raw in markets_payload:
                if not isinstance(raw, dict):
                    continue
                try:
                    markets.append(self._normalize_market(raw))
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning("Failed to normalize Kalshi market %s: %s", raw, exc)
                    continue

        return KalshiMarketsResponse(markets=markets, cursor=cursor)

    async def get_market(self, ticker: str) -> KalshiMarket:
        """Fetch single market details (public endpoint, no auth required)."""
        session = await get_session()
        path = f"/markets/{ticker}"
        url = f"{self.base_url}{path}"

        headers = {}
        if self.authenticator:
            headers.update(self.authenticator.sign_request("GET", path))

        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("Kalshi market detail failed: %s - %s", response.status, text)
                raise KalshiIntegrationError(
                    f"Kalshi market {ticker} request failed with status {response.status}: {text}"
                )
            payload = await response.json()

        raw_market = payload.get("market") if isinstance(payload, dict) else None
        if not isinstance(raw_market, dict):
            raise KalshiIntegrationError("Unexpected response payload for market detail")
        return self._normalize_market(raw_market)

    async def get_balance(self) -> Dict[str, Any]:
        """Get portfolio balance (requires authentication)."""
        if not self.authenticator:
            raise KalshiIntegrationError(
                "Authentication required for portfolio endpoints. "
                "Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH."
            )

        session = await get_session()
        path = "/portfolio/balance"
        url = f"{self.base_url}{path}"
        headers = self.authenticator.sign_request("GET", path)

        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("Kalshi balance request failed: %s - %s", response.status, text)
                raise KalshiIntegrationError(
                    f"Kalshi balance request failed with status {response.status}: {text}"
                )
            return await response.json()

    async def get_positions(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get portfolio positions (requires authentication)."""
        if not self.authenticator:
            raise KalshiIntegrationError(
                "Authentication required for portfolio endpoints. "
                "Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH."
            )

        session = await get_session()
        path = "/portfolio/positions"
        url = f"{self.base_url}{path}"
        headers = self.authenticator.sign_request("GET", path)
        query = dict(params or {})

        async with session.get(url, params=query, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                logger.error("Kalshi positions request failed: %s - %s", response.status, text)
                raise KalshiIntegrationError(
                    f"Kalshi positions request failed with status {response.status}: {text}"
                )
            return await response.json()

    def _normalize_market(self, raw: Dict[str, Any]) -> KalshiMarket:
        ticker = str(raw.get("ticker", "")).strip()
        if not ticker:
            raise KalshiIntegrationError("Market payload missing ticker")

        return KalshiMarket(
            ticker=ticker,
            title=str(raw.get("title") or "").strip(),
            subtitle=str(raw.get("subtitle") or "").strip() or None,
            event_ticker=str(raw.get("event_ticker") or "").strip() or None,
            status=str(raw.get("status") or "unknown").lower(),
            category=str(raw.get("category") or "").strip() or None,
            open_time=_normalize_timestamp(raw.get("open_time")),
            close_time=_normalize_timestamp(raw.get("close_time")),
            yes_bid=_safe_cents_price(raw.get("yes_bid")),
            yes_ask=_safe_cents_price(raw.get("yes_ask")),
            no_bid=_safe_cents_price(raw.get("no_bid")),
            no_ask=_safe_cents_price(raw.get("no_ask")),
            last_price=_safe_cents_price(raw.get("last_price")),
            volume=_safe_float(raw.get("volume")),
            volume_24h=_safe_float(raw.get("volume_24h")),
            open_interest=_safe_float(raw.get("open_interest")),
            liquidity=_safe_float(raw.get("liquidity")),
            url=f"{self.market_url_base}/{ticker}",
        )


class KalshiMarketListInput(BaseModel):
    """Input schema for market listing."""

    limit: int = Field(50, ge=1, le=1000, description="Number of markets to retrieve")
    cursor: Optional[str] = Field(
        default=None, description="Pagination cursor returned from previous call"
    )
    status: Optional[str] = Field(
        default="open",
        description="Comma-separated list of statuses (unopened, open, closed, settled)",
    )
    event_ticker: Optional[str] = Field(
        default=None, description="Filter by event ticker (comma-separated for multiple)"
    )
    series_ticker: Optional[str] = Field(
        default=None, description="Filter by series ticker (comma-separated for multiple)"
    )
    tickers: Optional[str] = Field(
        default=None, description="Filter by specific market tickers (comma-separated)"
    )
    min_close_ts: Optional[int] = Field(
        default=None, ge=0, description="Only include markets closing after this UNIX timestamp"
    )
    max_close_ts: Optional[int] = Field(
        default=None, ge=0, description="Only include markets closing before this UNIX timestamp"
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        tokens = [token.strip().lower() for token in value.split(",") if token.strip()]
        if not tokens:
            return None
        allowed = {"unopened", "open", "closed", "settled"}
        for token in tokens:
            if token not in allowed:
                raise ValueError(f"Invalid status '{token}'. Allowed values: {sorted(allowed)}")
        # Preserve order while removing duplicates
        seen = set()
        ordered = []
        for token in tokens:
            if token not in seen:
                ordered.append(token)
                seen.add(token)
        return ",".join(ordered)


class KalshiMarketDetailInput(BaseModel):
    ticker: str = Field(..., description="Kalshi market ticker, e.g. 'INFLATION23-YES'")

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        ticker = value.strip()
        if not ticker:
            raise ValueError("Ticker must not be empty")
        return ticker


class KalshiBalanceInput(BaseModel):
    """Input schema for balance query (no parameters needed)."""

    pass


class KalshiPositionsInput(BaseModel):
    """Input schema for positions query."""

    limit: int = Field(100, ge=1, le=1000, description="Number of positions to retrieve")
    cursor: Optional[str] = Field(
        default=None, description="Pagination cursor returned from previous call"
    )
    event_ticker: Optional[str] = Field(
        default=None, description="Filter by event ticker (comma-separated for multiple)"
    )
    settlement_status: Optional[str] = Field(
        default=None, description="Filter by settlement status (settled, unsettled)"
    )


class KalshiOpportunityInput(BaseModel):
    limit: int = Field(5, ge=1, le=20, description="Number of highlighted ideas to return")
    universe_limit: int = Field(
        120,
        ge=10,
        le=500,
        description="Number of markets to scan before ranking opportunities",
    )
    min_volume_24h: float = Field(
        100.0,
        ge=0.0,
        description="Minimum 24h contract volume required (Kalshi uses contracts, not USD)",
    )
    min_liquidity: float = Field(
        50.0,
        ge=0.0,
        description="Minimum liquidity score required (Kalshi-specific metric, typically 50-5000)",
    )
    max_yes_ask: float = Field(
        0.75, ge=0.01, le=0.99, description="Maximum yes-price to consider for long exposure"
    )
    event_ticker: Optional[str] = Field(
        default=None, description="Restrict to specific event tickers (comma-separated)"
    )
    category: Optional[str] = Field(
        default=None, description="Client-side filter by category string"
    )


class KalshiStrategyBriefInput(BaseModel):
    """Input schema for strategy brief generation."""

    count: int = Field(3, ge=1, le=10, description="Number of strategy ideas to return")
    universe_limit: int = Field(
        120,
        ge=20,
        le=500,
        description="Number of markets to scan before crafting strategies",
    )
    min_volume_24h: float = Field(
        100.0, ge=0.0, description="Minimum 24h volume required (contracts)"
    )
    min_liquidity: float = Field(
        50.0, ge=0.0, description="Minimum liquidity required (Kalshi metric)"
    )
    max_yes_ask: float = Field(0.75, ge=0.01, le=0.99, description="Maximum yes-price to consider")
    event_ticker: Optional[str] = Field(
        default=None, description="Restrict to specific event tickers"
    )
    category: Optional[str] = Field(default=None, description="Filter by category")


class KalshiTools:
    """Tool collection providing friendly access to Kalshi market data and portfolio."""

    def __init__(self, client: Optional[KalshiClient] = None) -> None:
        self.client = client or KalshiClient.from_settings()
        logger.info("Initialized Kalshi tools")

    async def list_markets(self, args: Dict[str, Any]) -> Dict[str, Any]:
        params = KalshiMarketListInput(**args)
        query: Dict[str, Any] = {"limit": params.limit}
        if params.cursor:
            query["cursor"] = params.cursor
        if params.status:
            query["status"] = params.status
        if params.event_ticker:
            query["event_ticker"] = params.event_ticker
        if params.series_ticker:
            query["series_ticker"] = params.series_ticker
        if params.tickers:
            query["tickers"] = params.tickers
        if params.min_close_ts:
            query["min_close_ts"] = params.min_close_ts
        if params.max_close_ts:
            query["max_close_ts"] = params.max_close_ts

        response = await self.client.get_markets(query)
        summaries = [self._summarize_market(market) for market in response.markets]
        return {
            "success": True,
            "count": len(summaries),
            "cursor": response.cursor,
            "markets": summaries,
            "note": (
                "Kalshi market data uses cents pricing. Prices shown as dollar probabilities."
            ),
        }

    async def market_details(self, args: Dict[str, Any]) -> Dict[str, Any]:
        params = KalshiMarketDetailInput(**args)
        market = await self.client.get_market(params.ticker)
        summary = self._summarize_market(market, include_extended=True)
        summary["success"] = True
        summary["disclaimer"] = (
            "Kalshi market data is delayed and indicative. Confirm latest order book before trading."
        )
        return summary

    async def get_balance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get portfolio balance."""
        try:
            result = await self.client.get_balance()
            result["success"] = True
            return result
        except KalshiIntegrationError as e:
            return {"success": False, "error": str(e)}

    async def get_positions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get portfolio positions with market and event details."""
        try:
            params = KalshiPositionsInput(**args)
            query: Dict[str, Any] = {"limit": params.limit}
            if params.cursor:
                query["cursor"] = params.cursor
            if params.event_ticker:
                query["event_ticker"] = params.event_ticker
            if params.settlement_status:
                query["settlement_status"] = params.settlement_status

            result = await self.client.get_positions(query)

            # Format positions for readability
            formatted_result = {
                "success": True,
                "cursor": result.get("cursor"),
                "market_positions": result.get("market_positions", []),
                "event_positions": result.get("event_positions", []),
                "summary": {
                    "total_market_positions": len(result.get("market_positions", [])),
                    "total_event_positions": len(result.get("event_positions", [])),
                },
            }
            return formatted_result
        except KalshiIntegrationError as e:
            return {"success": False, "error": str(e)}

    async def scan_opportunities(self, args: Dict[str, Any]) -> Dict[str, Any]:
        params = KalshiOpportunityInput(**args)
        query: Dict[str, Any] = {"limit": params.universe_limit, "status": "open"}
        if params.event_ticker:
            query["event_ticker"] = params.event_ticker

        response = await self.client.get_markets(query)
        filtered = [
            market
            for market in response.markets
            if (not params.category or (market.category or "").lower() == params.category.lower())
        ]
        ranked = self._rank_opportunities(
            filtered,
            limit=params.limit,
            min_volume=params.min_volume_24h,
            min_liquidity=params.min_liquidity,
            max_yes_ask=params.max_yes_ask,
        )

        return {
            "success": True,
            "opportunities": ranked,
            "scanned_markets": len(filtered),
            "parameters": {
                "min_volume_24h": params.min_volume_24h,
                "min_liquidity": params.min_liquidity,
                "max_yes_ask": params.max_yes_ask,
                "event_ticker": params.event_ticker,
                "category": params.category,
            },
            "note": (
                "Volume in contracts (not USD). Kalshi liquidity metric differs from Polymarket. "
                "Binary markets: each market is one Yes/No opportunity."
            ),
            "disclaimer": (
                "Heuristic scoring only. Review Kalshi order books and official rules before trading."
            ),
        }

    async def strategy_brief(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate trade ideas with entry/exit/TP/SL suggestions."""
        params = KalshiStrategyBriefInput(**args)
        query: Dict[str, Any] = {"limit": params.universe_limit, "status": "open"}
        if params.event_ticker:
            query["event_ticker"] = params.event_ticker

        response = await self.client.get_markets(query)
        filtered = [
            market
            for market in response.markets
            if (not params.category or (market.category or "").lower() == params.category.lower())
        ]

        # Get ranked opportunities
        ranked = self._rank_opportunities(
            filtered,
            limit=params.count,
            min_volume=params.min_volume_24h,
            min_liquidity=params.min_liquidity,
            max_yes_ask=params.max_yes_ask,
        )

        # Convert to strategy views with TP/SL
        strategies = [self._craft_strategy_view(opp) for opp in ranked]

        return {
            "success": True,
            "strategies": strategies,
            "scanned_markets": len(filtered),
            "note": (
                "Generated heuristics only. Confirm liquidity, spreads, and market rules before trading. "
                "TP/SL levels are algorithmic suggestions, not financial advice."
            ),
        }

    def _summarize_market(
        self, market: KalshiMarket, *, include_extended: bool = False
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "ticker": market.ticker,
            "title": market.title,
            "subtitle": market.subtitle,
            "status": market.status,
            "category": market.category,
            "event_ticker": market.event_ticker,
            "open_time": market.open_time,
            "close_time": market.close_time,
            "yes_bid": market.yes_bid,
            "yes_ask": market.yes_ask,
            "no_bid": market.no_bid,
            "no_ask": market.no_ask,
            "last_price": market.last_price,
            "volume": market.volume,
            "volume_24h": market.volume_24h,
            "open_interest": market.open_interest,
            "liquidity": market.liquidity,
            "market_url": market.url,
        }
        if market.entry_price is not None and market.entry_price > 0:
            summary["implied_probability"] = round(market.entry_price, 4)
            summary["returns_if_yes_resolves"] = round(
                (1.0 - market.entry_price) / market.entry_price, 3
            )
        if include_extended:
            summary.update(
                {
                    "notes": (
                        "Values expressed in dollars and contracts. "
                        "Liquidity metric is Kalshi-provided heuristic."
                    ),
                }
            )
        return summary

    def _rank_opportunities(
        self,
        universe: List[KalshiMarket],
        *,
        limit: int,
        min_volume: float,
        min_liquidity: float,
        max_yes_ask: float,
    ) -> List[Dict[str, Any]]:
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for market in universe:
            entry_price = market.entry_price
            if entry_price is None:
                continue
            if entry_price <= 0 or entry_price > max_yes_ask:
                continue
            volume_24h = market.volume_24h or 0.0
            liquidity = market.liquidity or 0.0
            if volume_24h < min_volume:
                continue
            if liquidity < min_liquidity:
                continue

            roi = (1.0 - entry_price) / entry_price
            if roi <= 0:
                continue

            spread_component = 0.0
            if market.yes_ask is not None and market.yes_bid is not None:
                spread = max(0.0, market.yes_ask - market.yes_bid)
                spread_component = max(0.0, 0.04 - spread)

            volume_component = math.log1p(volume_24h)
            liquidity_component = math.log1p(liquidity)

            score = (
                roi * (1.0 + 0.6 * volume_component + 0.4 * liquidity_component)
            ) + spread_component
            scored.append(
                (
                    score,
                    {
                        "ticker": market.ticker,
                        "title": market.title,
                        "subtitle": market.subtitle,
                        "event_ticker": market.event_ticker,
                        "category": market.category,
                        "entry_price": round(entry_price, 4),
                        "yes_bid": market.yes_bid,
                        "yes_ask": market.yes_ask,
                        "implied_probability": round(entry_price, 4),
                        "roi_if_yes_resolves": round(roi, 2),
                        "volume_24h": volume_24h,
                        "open_interest": market.open_interest,
                        "liquidity": liquidity,
                        "market_url": market.url,
                        "score": round(score, 4),
                        "notes": (
                            "Higher volume/liquidity and tighter spreads increase the score. "
                            "Verify order depth before executing."
                        ),
                    },
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def _craft_strategy_view(self, idea: Dict[str, Any]) -> Dict[str, Any]:
        """Generate entry/exit strategy with TP/SL levels for a market opportunity."""
        entry_price = idea["entry_price"]

        # Calculate take profit and stop loss based on entry price
        # Lower entry = more room for upside, adjust accordingly
        if entry_price <= 0.35:
            # Deep value plays - wider stops, aggressive targets
            take_profit = min(0.99, round(entry_price + 0.30, 3))
            stop_loss = max(0.01, round(entry_price - 0.15, 3))
        elif entry_price <= 0.55:
            # Medium conviction - balanced approach
            take_profit = min(0.95, round(entry_price + 0.25, 3))
            stop_loss = max(0.05, round(entry_price - 0.15, 3))
        else:
            # Higher probability plays - tighter management
            take_profit = min(0.92, round(entry_price + 0.18, 3))
            stop_loss = max(0.10, round(entry_price - 0.12, 3))

        # Calculate risk-reward ratio
        risk = max(0.01, entry_price - stop_loss)
        reward = take_profit - entry_price
        risk_reward = round(reward / risk, 2)

        # Generate trading guidance
        if entry_price < 0.40:
            guidance = (
                "Underpriced opportunity. Enter with limit orders near the ask. "
                "Scale in if price dips further. Take profits incrementally above TP level. "
                "Monitor for news catalysts that could accelerate movement."
            )
        elif entry_price < 0.60:
            guidance = (
                "Balanced entry point. Use limit orders between bid and ask. "
                "Set alerts at TP/SL levels. Consider scaling out 50% at TP, "
                "letting remaining position run with trailing stop."
            )
        else:
            guidance = (
                "Higher probability play with limited upside. Enter cautiously. "
                "Use tight stops due to reduced margin of safety. "
                "Take profits quickly as small movements matter more at this level."
            )

        return {
            "ticker": idea["ticker"],
            "title": idea["title"],
            "event_ticker": idea.get("event_ticker"),
            "category": idea.get("category"),
            "entry_price": entry_price,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "risk_reward_ratio": risk_reward,
            "implied_probability": idea["implied_probability"],
            "roi_if_yes_resolves": idea["roi_if_yes_resolves"],
            "volume_24h": idea["volume_24h"],
            "liquidity": idea["liquidity"],
            "market_url": idea["market_url"],
            "score": idea["score"],
            "trading_notes": guidance,
            "disclaimer": "Algorithmic suggestions only. Not financial advice. DYOR.",
        }


def create_kalshi_tools(kalshi_tools: KalshiTools) -> List[Tool]:
    async def handle_market_list(args: Dict[str, Any]) -> Dict[str, Any]:
        return await kalshi_tools.list_markets(args)

    async def handle_market_detail(args: Dict[str, Any]) -> Dict[str, Any]:
        return await kalshi_tools.market_details(args)

    async def handle_opportunity_scan(args: Dict[str, Any]) -> Dict[str, Any]:
        return await kalshi_tools.scan_opportunities(args)

    async def handle_strategy_brief(args: Dict[str, Any]) -> Dict[str, Any]:
        return await kalshi_tools.strategy_brief(args)

    async def handle_get_balance(args: Dict[str, Any]) -> Dict[str, Any]:
        return await kalshi_tools.get_balance(args)

    async def handle_get_positions(args: Dict[str, Any]) -> Dict[str, Any]:
        return await kalshi_tools.get_positions(args)

    return [
        Tool(
            spec=ToolSpec(
                name="kalshi_list_markets",
                description="Fetch Kalshi markets with pricing and volume data",
                namespace="kalshi",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 50,
                            "description": "Number of markets to return",
                        },
                        "cursor": {
                            "type": "string",
                            "description": "Pagination cursor returned from prior call",
                        },
                        "status": {
                            "type": "string",
                            "description": "Comma separated list of statuses (unopened, open, closed, settled)",
                        },
                        "event_ticker": {
                            "type": "string",
                            "description": "Filter by event ticker(s)",
                        },
                        "series_ticker": {
                            "type": "string",
                            "description": "Filter by series ticker(s)",
                        },
                        "tickers": {
                            "type": "string",
                            "description": "Filter by specific market tickers (comma-separated)",
                        },
                        "min_close_ts": {
                            "type": "integer",
                            "description": "Only include markets closing after this UNIX timestamp",
                        },
                        "max_close_ts": {
                            "type": "integer",
                            "description": "Only include markets closing before this UNIX timestamp",
                        },
                    },
                },
            ),
            handler=handle_market_list,
            input_model=KalshiMarketListInput,
        ),
        Tool(
            spec=ToolSpec(
                name="kalshi_market_overview",
                description="Return detailed Kalshi market snapshot with trade heuristics",
                namespace="kalshi",
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Kalshi market ticker identifier",
                        }
                    },
                    "required": ["ticker"],
                },
            ),
            handler=handle_market_detail,
            input_model=KalshiMarketDetailInput,
        ),
        Tool(
            spec=ToolSpec(
                name="kalshi_opportunity_scan",
                description="Rank Kalshi markets by ROI, liquidity, and volume heuristics",
                namespace="kalshi",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5,
                            "description": "Number of highlighted opportunities to return",
                        },
                        "universe_limit": {
                            "type": "integer",
                            "minimum": 10,
                            "maximum": 500,
                            "default": 120,
                            "description": "Number of markets to scan before ranking",
                        },
                        "min_volume_24h": {
                            "type": "number",
                            "minimum": 0,
                            "default": 100,
                            "description": "Minimum 24h contract volume required (Kalshi uses contracts)",
                        },
                        "min_liquidity": {
                            "type": "number",
                            "minimum": 0,
                            "default": 50,
                            "description": "Minimum liquidity metric required (Kalshi-specific)",
                        },
                        "max_yes_ask": {
                            "type": "number",
                            "minimum": 0.01,
                            "maximum": 0.99,
                            "default": 0.75,
                            "description": "Maximum yes-price considered for opportunity ranking",
                        },
                        "event_ticker": {
                            "type": "string",
                            "description": "Restrict to event ticker(s)",
                        },
                        "category": {
                            "type": "string",
                            "description": "Restrict to markets whose category matches this string",
                        },
                    },
                },
            ),
            handler=handle_opportunity_scan,
            input_model=KalshiOpportunityInput,
        ),
        Tool(
            spec=ToolSpec(
                name="kalshi_strategy_brief",
                description="Generate Kalshi trade ideas with entry/exit/TP/SL strategy suggestions",
                namespace="kalshi",
                input_schema={
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 3,
                            "description": "Number of strategy ideas to return",
                        },
                        "universe_limit": {
                            "type": "integer",
                            "minimum": 20,
                            "maximum": 500,
                            "default": 120,
                            "description": "Number of markets to scan before generating strategies",
                        },
                        "min_volume_24h": {
                            "type": "number",
                            "minimum": 0,
                            "default": 100,
                            "description": "Minimum 24h volume required (contracts)",
                        },
                        "min_liquidity": {
                            "type": "number",
                            "minimum": 0,
                            "default": 50,
                            "description": "Minimum liquidity required (Kalshi metric)",
                        },
                        "max_yes_ask": {
                            "type": "number",
                            "minimum": 0.01,
                            "maximum": 0.99,
                            "default": 0.75,
                            "description": "Maximum yes-price to consider",
                        },
                        "event_ticker": {
                            "type": "string",
                            "description": "Restrict to specific event ticker(s)",
                        },
                        "category": {
                            "type": "string",
                            "description": "Filter by category",
                        },
                    },
                },
            ),
            handler=handle_strategy_brief,
            input_model=KalshiStrategyBriefInput,
        ),
        Tool(
            spec=ToolSpec(
                name="kalshi_get_balance",
                description="Get portfolio balance (requires authentication)",
                namespace="kalshi",
                input_schema={"type": "object", "properties": {}},
            ),
            handler=handle_get_balance,
            input_model=KalshiBalanceInput,
        ),
        Tool(
            spec=ToolSpec(
                name="kalshi_get_positions",
                description="Get portfolio positions (requires authentication)",
                namespace="kalshi",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100,
                            "description": "Number of positions to return",
                        },
                        "cursor": {
                            "type": "string",
                            "description": "Pagination cursor returned from prior call",
                        },
                        "event_ticker": {
                            "type": "string",
                            "description": "Filter by event ticker(s)",
                        },
                        "settlement_status": {
                            "type": "string",
                            "description": "Filter by settlement status (settled, unsettled)",
                        },
                    },
                },
            ),
            handler=handle_get_positions,
            input_model=KalshiPositionsInput,
        ),
    ]
