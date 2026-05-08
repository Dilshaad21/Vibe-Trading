"""Tests for INDMoney public types."""

from __future__ import annotations

import pytest

from src.integrations.indmoney.types import CashSnapshot, Holding


def test_holding_is_frozen():
    h = Holding(
        symbol="AAPL", name="Apple Inc",
        quantity=10.0, avg_cost=150.0, market_value=1700.0,
        unrealized_pnl=200.0, currency="USD",
        asset_class="us_equity", asof="2026-05-07T14:30:00+05:30",
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        h.symbol = "MSFT"  # type: ignore[misc]


def test_holding_to_dict_roundtrip():
    h = Holding(
        symbol="AAPL", name="Apple Inc",
        quantity=10.0, avg_cost=150.0, market_value=1700.0,
        unrealized_pnl=200.0, currency="USD",
        asset_class="us_equity", asof="2026-05-07T14:30:00+05:30",
    )
    d = h.to_dict()
    assert d["symbol"] == "AAPL"
    assert d["asset_class"] == "us_equity"
    assert Holding.from_dict(d) == h


def test_cash_snapshot_to_dict_roundtrip():
    c = CashSnapshot(cash_usd=500.0, cash_inr=12000.0, pending_settlement_usd=0.0,
                    asof="2026-05-07T14:30:00+05:30")
    assert CashSnapshot.from_dict(c.to_dict()) == c


def test_holding_asset_class_enum_values():
    # Allowed values per spec section 5.
    for ac in ("us_equity", "us_etf", "indian_equity", "mf"):
        h = Holding(symbol="X", name="x", quantity=1, avg_cost=1, market_value=1,
                    unrealized_pnl=0, currency="USD", asset_class=ac, asof="2026-05-07")
        assert h.asset_class == ac
