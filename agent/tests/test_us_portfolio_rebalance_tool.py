"""US sleeve calculations use the INDMoney wallet and remain read-only."""

from __future__ import annotations

import json

import pytest

from src.tools.us_portfolio_rebalance_tool import (
    USPortfolioRebalanceTool,
    calculate_us_rebalance,
)


@pytest.fixture
def snapshot():
    return {
        "currency": "USD",
        "asof": "2026-09-20",
        "snapshot_path": "/tmp/holdings.json",
        "from_cache": False,
        "holdings": [
            {"symbol": "AAA", "asset_class": "us_equity", "currency": "USD", "market_value": 60, "quantity": 3},
            {"symbol": "BBB", "asset_class": "us_equity", "currency": "USD", "market_value": 40, "quantity": 2},
            {"symbol": "IND", "asset_class": "indian_equity", "currency": "USD", "market_value": 500, "quantity": 10},
        ],
        "investments_by_asset_type": [
            {"asset_type": "US_STOCK", "current_value": 100},
            {"asset_type": "US_STOCK_WALLET", "current_value": 20},
        ],
        "cash": {"cash_usd": 700},
    }


def test_calculator_uses_us_wallet_and_sizes_partial_targets(snapshot):
    result = calculate_us_rebalance(snapshot, {"AAA": 40, "BBB": 60})

    assert result["sleeve_value_usd"] == 120
    assert result["us_wallet_usd"] == 20
    assert result["stock_count"] == 2
    assert result["top_five_weight_pct"] == pytest.approx(83.333, abs=0.001)
    assert result["trades"] == [
        {"symbol": "AAA", "side": "sell", "amount_usd": 12, "approx_shares": 0.6, "target_weight_pct": 40},
        {"symbol": "BBB", "side": "buy", "amount_usd": 32, "approx_shares": 1.6, "target_weight_pct": 60},
    ]
    assert result["remaining_us_wallet_usd"] == 0
    assert result["funded_by_wallet_and_sells"] is True
    assert result["execution"] == "analysis_only"


def test_calculator_keeps_omitted_holding_and_reports_funding_gap(snapshot):
    result = calculate_us_rebalance(snapshot, {"AAA": 70})

    assert len(result["trades"]) == 1
    assert result["trades"][0]["amount_usd"] == 24
    assert result["remaining_us_wallet_usd"] == -4
    assert result["funding_gap_usd"] == 4
    assert result["funded_by_wallet_and_sells"] is False
    assert "target_weight_pct" not in next(h for h in result["holdings"] if h["symbol"] == "BBB")


@pytest.mark.parametrize("change", [
    {"currency": "INR"},
    {"investments_by_asset_type": []},
])
def test_calculator_rejects_unusable_snapshot(snapshot, change):
    snapshot.update(change)
    with pytest.raises(ValueError):
        calculate_us_rebalance(snapshot)


def test_tool_propagates_holdings_auth_error(monkeypatch):
    monkeypatch.setattr(
        "src.tools.us_portfolio_rebalance_tool.IndMoneyHoldingsTool.execute",
        lambda self, **kwargs: json.dumps({"ok": False, "error_kind": "needs_auth", "message": "login"}),
    )
    result = json.loads(USPortfolioRebalanceTool().execute(force_refresh=True))
    assert result == {"ok": False, "error_kind": "needs_auth", "message": "login"}


def test_tool_analyzes_labeled_saved_snapshot(tmp_path, monkeypatch, snapshot):
    folder = tmp_path / "indmoney"
    folder.mkdir()
    path = folder / "account_holdings_123.json"
    path.write_text(json.dumps(snapshot))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))

    result = json.loads(USPortfolioRebalanceTool().execute(snapshot_path=str(path), target_weights_pct={"AAA": 40}))

    assert result["ok"] is True
    assert result["snapshot_source"] == "saved_snapshot"
    assert result["snapshot_path"] == str(path)
    assert result["snapshot_file_mtime_utc"]
    assert result["from_cache"] is True


def test_tool_rejects_saved_file_outside_indmoney_dir(tmp_path, monkeypatch, snapshot):
    path = tmp_path / "account_holdings_123.json"
    path.write_text(json.dumps(snapshot))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))

    result = json.loads(USPortfolioRebalanceTool().execute(snapshot_path=str(path)))

    assert result["ok"] is False
    assert result["error_kind"] == "invalid_snapshot_path"


def test_mcp_exposes_calculator():
    import asyncio
    import mcp_server

    names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "us_portfolio_rebalance" in names
