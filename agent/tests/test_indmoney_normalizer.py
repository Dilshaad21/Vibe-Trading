"""Tests for INDMoney normalizer.

The v1 trades/events split is gone — INDMoney's MCP has no transaction
stream, so there are no trades or events to write. Only the v2
networth-shape tests remain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.integrations.indmoney.normalizer import (
    normalize_networth_holdings,
    normalize_networth_snapshot,
)

FIX = Path(__file__).parent / "fixtures/indmoney"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_normalize_networth_holdings_us_stock_uses_investment_code_as_symbol():
    holdings = normalize_networth_holdings(
        "US_STOCK", _load("networth_holdings_us_stock.json"))
    assert len(holdings) == 2
    h1, h2 = holdings
    # Symbol = INDMoney's investment_code (we don't have ticker resolution in v1).
    assert h1.symbol == "100001"
    assert h1.name == "Example US Equity One"
    assert h1.asset_class == "us_equity"
    assert h1.currency == "INR", "INDMoney returns INR-denominated values for US stocks"
    assert h1.quantity == 0.5
    # avg_cost is per-unit (invested_amount / total_units).
    assert h1.avg_cost == pytest.approx(60000.0)
    assert h1.market_value == 32000.0
    assert h1.unrealized_pnl == 2000.0


def test_normalize_networth_holdings_ind_stock_marks_indian_equity():
    holdings = normalize_networth_holdings(
        "IND_STOCK", _load("networth_holdings_ind_stock.json"))
    assert len(holdings) == 1
    assert holdings[0].asset_class == "indian_equity"
    assert holdings[0].symbol == "200001"
    assert holdings[0].currency == "INR"


def test_normalize_networth_holdings_zero_units_does_not_divide_by_zero():
    payload = {
        "holdings": [{
            "investment_code": "300001", "investment": "Zero Units",
            "asset_type": "US_STOCK", "assetclass_l2": "Global Equity",
            "invested_amount": 0, "market_value": 0,
            "total_pnl": 0, "total_units": 0, "unit_price": 0,
        }]
    }
    holdings = normalize_networth_holdings("US_STOCK", payload)
    assert len(holdings) == 1
    assert holdings[0].quantity == 0
    assert holdings[0].avg_cost == 0  # safe fallback when total_units == 0


def test_normalize_networth_holdings_mf_marks_mf():
    payload = {"holdings": [{
        "investment_code": "400001", "investment": "Example MF Scheme",
        "asset_type": "MF", "assetclass_l2": "Indian Equity",
        "invested_amount": 100000, "market_value": 110000,
        "total_pnl": 10000, "total_units": 10, "unit_price": 11000,
    }]}
    holdings = normalize_networth_holdings("MF", payload)
    assert holdings[0].asset_class == "mf"


def test_normalize_networth_holdings_unknown_asset_type_falls_back_to_other():
    payload = {"holdings": [{
        "investment_code": "500001", "investment": "Some Bond",
        "asset_type": "BOND", "assetclass_l2": "Debt",
        "invested_amount": 50000, "market_value": 51000,
        "total_pnl": 1000, "total_units": 1, "unit_price": 51000,
    }]}
    holdings = normalize_networth_holdings("BOND", payload)
    assert holdings[0].asset_class == "other"


def test_normalize_networth_holdings_handles_unknown_string_in_invested_amount():
    """Real-world finding from the live smoke: some legacy positions return
    the literal string 'unknown' for invested_amount / market_value /
    total_pnl. Float coercion must default these to 0 instead of raising."""
    payload = {"holdings": [{
        "investment_code": "999001", "investment": "Legacy Stock",
        "asset_type": "IND_STOCK", "assetclass_l2": "Indian Equity",
        "invested_amount": "unknown",
        "market_value": "unknown",
        "total_pnl": "unknown",
        "total_units": 100.0, "unit_price": 0,
    }]}
    holdings = normalize_networth_holdings("IND_STOCK", payload)
    assert len(holdings) == 1
    assert holdings[0].quantity == 100.0
    assert holdings[0].avg_cost == 0.0
    assert holdings[0].market_value == 0.0
    assert holdings[0].unrealized_pnl == 0.0


def test_normalize_networth_holdings_empty_payload():
    assert normalize_networth_holdings("US_STOCK", {}) == []
    assert normalize_networth_holdings("US_STOCK", {"holdings": []}) == []


def test_normalize_networth_snapshot_extracts_totals():
    snap = normalize_networth_snapshot(_load("networth_snapshot.json"))
    assert snap["total_invested"] == 600000.0
    assert snap["total_current_value"] == 4000000.0
    assert snap["total_networth"] == 4000000.0
    # Per-asset-type lookup is preserved verbatim for downstream use.
    by_type = {item["asset_type"]: item for item in snap["investments"]}
    assert "STOCK" in by_type
    assert "US_STOCK" in by_type
    # Liquid assetclass surfaces in the assets array (used as cash proxy).
    by_class = {item["assetclass_l2"]: item for item in snap["assets"]}
    assert "Liquid" in by_class
    assert by_class["Liquid"]["current_value"] == 700000.0


def test_normalize_networth_snapshot_missing_fields_defaults_to_zero():
    snap = normalize_networth_snapshot({})
    assert snap["total_invested"] == 0.0
    assert snap["total_current_value"] == 0.0
    assert snap["total_networth"] == 0.0
    assert snap["investments"] == []
    assert snap["assets"] == []
