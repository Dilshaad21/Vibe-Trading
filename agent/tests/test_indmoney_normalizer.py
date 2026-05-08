"""Tests for INDMoney normalizer + CSV writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.integrations.indmoney.normalizer import (
    normalize_cash,
    normalize_holdings,
    normalize_transactions,
    write_events_csv,
    write_trades_csv,
)
from src.integrations.indmoney.types import CashSnapshot, Holding
from src.tools.trade_journal_parsers import (
    TradeRecord,
    load_dataframe,
    parse_generic,
)

FIX = Path(__file__).parent / "fixtures/indmoney"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_normalize_holdings_marks_us_equity_and_etf():
    holdings = normalize_holdings(_load("holdings.json"))
    assert isinstance(holdings, list)
    by_sym = {h.symbol: h for h in holdings}
    assert by_sym["AAPL"].asset_class == "us_equity"
    assert by_sym["VOO"].asset_class == "us_etf"
    assert by_sym["RELIANCE.NS"].asset_class == "indian_equity"
    assert by_sym["AAPL"].currency == "USD"
    assert by_sym["RELIANCE.NS"].currency == "INR"
    assert by_sym["AAPL"].quantity == 10.5  # fractional preserved


def test_normalize_cash_returns_snapshot():
    cash = normalize_cash(_load("cash.json"))
    assert isinstance(cash, CashSnapshot)
    assert cash.cash_usd == 1234.56
    assert cash.cash_inr == 5000.0
    assert cash.pending_settlement_usd == 100.0


def test_normalize_transactions_splits_trades_from_events():
    trades, events = normalize_transactions(_load("transactions.json"))

    assert all(isinstance(t, TradeRecord) for t in trades)
    assert {t.side for t in trades} == {"buy", "sell"}, "non-buy/sell rows must NOT enter trades"
    assert len(trades) == 2  # buy + sell only

    assert len(events) == 3
    kinds = {e["event_type"] for e in events}
    assert kinds == {"dividend", "split", "unknown"}


def test_normalize_transactions_records_fx_in_notes():
    trades, _ = normalize_transactions(_load("transactions.json"))
    aapl_buy = next(t for t in trades if t.side == "buy")
    # The TradeRecord schema does not have a `notes` field; we encode FX
    # inside `name` as a parenthesized suffix to remain schema-compatible.
    assert "fx_usd_inr=83.2" in aapl_buy.name


def test_normalize_us_market_value_is_us():
    trades, _ = normalize_transactions(_load("transactions.json"))
    for t in trades:
        assert t.market == "us"


def test_write_trades_csv_roundtrips_through_parse_generic(tmp_path: Path):
    """Critical contract: trades CSV must NOT be collapsed by _normalize_side."""
    trades, _ = normalize_transactions(_load("transactions.json"))
    csv_path = tmp_path / "trades.csv"
    write_trades_csv(trades, csv_path)

    df = load_dataframe(csv_path)
    parsed = parse_generic(df)

    # Sides preserved (no silent buy-coercion).
    assert {t.side for t in parsed} == {t.side for t in trades}
    assert len(parsed) == len(trades)


def test_write_events_csv_columns(tmp_path: Path):
    _, events = normalize_transactions(_load("transactions.json"))
    csv_path = tmp_path / "events.csv"
    write_events_csv(events, csv_path)

    with csv_path.open() as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == [
        "datetime", "symbol", "event_type", "quantity_delta",
        "cash_delta", "ratio", "currency", "notes",
    ]


def test_write_events_csv_unknown_event_preserves_payload(tmp_path: Path):
    _, events = normalize_transactions(_load("transactions.json"))
    weird = next(e for e in events if e["event_type"] == "unknown")
    assert "weird_thing" in weird["notes"]


def test_normalize_handles_empty_collections():
    assert normalize_holdings({"positions": [], "account_id": "X", "asof": ""}) == []
    trades, events = normalize_transactions({"items": [], "account_id": "X"})
    assert trades == []
    assert events == []
