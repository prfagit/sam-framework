import pytest

from sam.integrations.polymarket import (
    _parse_outcomes,
    MarketOutcome,
    MarketSnapshot,
    PolymarketTools,
)


def test_parse_outcomes_from_string_lists():
    raw = {
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.42", "0.58"]',
    }
    outcomes = _parse_outcomes(raw)
    assert len(outcomes) == 2
    assert outcomes[0].name == "Yes"
    assert outcomes[0].price == pytest.approx(0.42)
    assert outcomes[1].roi == pytest.approx((1 / 0.58) - 1)


def test_rank_opportunities_prioritizes_roi_with_volume():
    tools = PolymarketTools()
    market = MarketSnapshot(
        id="1",
        question="Will the sample event happen?",
        slug="sample-market",
        category="sports",
        end_date="2025-01-01T00:00:00+00:00",
        outcomes=[MarketOutcome("Yes", 0.3), MarketOutcome("No", 0.7)],
        volume_24h=5000.0,
        volume_total=6000.0,
        liquidity=2000.0,
        best_bid=0.29,
        best_ask=0.31,
        updated_at=None,
        url="https://polymarket.com/market/sample-market",
    )

    ideas = tools._rank_opportunities(
        [market],
        limit=3,
        min_volume=100.0,
        min_liquidity=100.0,
        max_entry_price=0.5,
    )

    assert ideas
    top = ideas[0]
    assert top["market_id"] == "1"
    assert top["outcome"] == "Yes"
    assert top["entry_price"] == pytest.approx(0.3)
    assert top["roi_if_win"] > 2.0


def test_rank_opportunities_filters_low_volume_and_price():
    tools = PolymarketTools()
    high_price_market = MarketSnapshot(
        id="2",
        question="High price outcome",
        slug=None,
        category=None,
        end_date=None,
        outcomes=[MarketOutcome("Yes", 0.9)],
        volume_24h=10000.0,
        volume_total=12000.0,
        liquidity=3000.0,
        best_bid=None,
        best_ask=None,
        updated_at=None,
        url=None,
    )

    low_volume_market = MarketSnapshot(
        id="3",
        question="Low volume outcome",
        slug=None,
        category=None,
        end_date=None,
        outcomes=[MarketOutcome("Yes", 0.2)],
        volume_24h=50.0,
        volume_total=60.0,
        liquidity=50.0,
        best_bid=None,
        best_ask=None,
        updated_at=None,
        url=None,
    )

    ideas = tools._rank_opportunities(
        [high_price_market, low_volume_market],
        limit=5,
        min_volume=500.0,
        min_liquidity=200.0,
        max_entry_price=0.6,
    )

    assert ideas == []


def test_strategy_view_generates_exit_and_stop():
    tools = PolymarketTools()
    idea = {
        "market_id": "42",
        "question": "Sample question",
        "outcome": "Yes",
        "entry_price": 0.45,
        "implied_probability": 0.45,
        "net_payout_if_win": 0.55,
        "roi_if_win": 1.22,
        "volume_24h": 5000.0,
        "liquidity": 2000.0,
        "best_bid": 0.44,
        "best_ask": 0.46,
        "market_url": "https://polymarket.com/market/sample",
        "ends_at": "2025-10-01T00:00:00+00:00",
        "score": 1.5,
    }

    strategy = tools._craft_strategy_view(idea)
    assert strategy["market_id"] == "42"
    assert 0.45 <= strategy["take_profit"] <= 0.99
    assert strategy["stop_loss"] < strategy["entry_price"]
    assert strategy["risk_reward_ratio"] > 0
    assert "limit order" in strategy["notes"].lower()
