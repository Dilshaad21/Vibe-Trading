"""End-to-end contract tests for MacroSnapshotTool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))


def _stub_snapshot() -> dict:
    return {
        "asof": "2026-05-09T14:30:00+00:00",
        "central_bank_rates": {"fed_funds_target_upper": 5.50,
                                "fed_funds_target_lower": 5.25},
        "yields": {"ust_2y": 4.81, "ust_10y": 4.34, "us_2s10s_bp": -47},
        "fx": {"usd_inr": 83.45, "dxy": 104.21},
        "commodities": {"gold_usd_oz": 2310.50},
        "_sources": {"fed_funds_target_upper": "FRED:DFEDTARU"},
        "_errors": [],
    }


def test_macro_snapshot_tool_happy_path(monkeypatch):
    """Fresh fetch returns ok=True, structured payload, snapshot_path exists."""
    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot",
        lambda **kw: _stub_snapshot(),
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    out = json.loads(MacroSnapshotTool().execute(force_refresh=True))
    assert out["ok"] is True
    assert out["from_cache"] is False
    assert out["fx"]["usd_inr"] == 83.45
    assert out["yields"]["us_2s10s_bp"] == -47
    assert Path(out["snapshot_path"]).exists()


def test_macro_snapshot_tool_uses_cache_within_ttl(monkeypatch):
    """Second call within TTL returns from_cache=True and never calls fetcher."""
    calls = {"n": 0}

    def counting_fetch(**kw):
        calls["n"] += 1
        return _stub_snapshot()

    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot", counting_fetch,
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    tool = MacroSnapshotTool()
    a = json.loads(tool.execute(force_refresh=True))
    b = json.loads(tool.execute())
    assert calls["n"] == 1
    assert a["from_cache"] is False
    assert b["from_cache"] is True
    assert b["fx"]["usd_inr"] == 83.45


def test_macro_snapshot_tool_force_refresh_skips_cache(monkeypatch):
    calls = {"n": 0}

    def counting_fetch(**kw):
        calls["n"] += 1
        return _stub_snapshot()

    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot", counting_fetch,
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    tool = MacroSnapshotTool()
    tool.execute(force_refresh=True)
    tool.execute(force_refresh=True)
    assert calls["n"] == 2


def test_macro_snapshot_tool_surfaces_errors(monkeypatch):
    """If the snapshot has _errors, they appear in the response unchanged."""
    payload = _stub_snapshot()
    payload["_errors"] = [
        {"field": "ecb_deposit", "source": "FRED:ECBDFR", "reason": "503"},
    ]
    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot", lambda **kw: payload,
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    out = json.loads(MacroSnapshotTool().execute(force_refresh=True))
    assert out["ok"] is True
    assert len(out["_errors"]) == 1
    assert out["_errors"][0]["field"] == "ecb_deposit"
