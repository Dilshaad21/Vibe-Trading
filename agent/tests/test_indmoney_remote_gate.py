"""Verify the VIBE_TRADING_ENABLE_INDMONEY gate for non-loopback callers."""

from __future__ import annotations

import json


def _exec_holdings():
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    return json.loads(IndMoneyHoldingsTool().execute())


def test_remote_caller_without_gate_is_blocked(monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_REMOTE_CALL", "1")
    monkeypatch.delenv("VIBE_TRADING_ENABLE_INDMONEY", raising=False)
    out = _exec_holdings()
    assert out["ok"] is False
    assert out["error_kind"] == "config_missing"


def test_remote_caller_with_gate_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_TRADING_REMOTE_CALL", "1")
    monkeypatch.setenv("VIBE_TRADING_ENABLE_INDMONEY", "1")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "missing.json",
    )
    out = _exec_holdings()
    assert out["error_kind"] == "needs_auth"


def test_local_caller_passes_without_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("VIBE_TRADING_REMOTE_CALL", raising=False)
    monkeypatch.delenv("VIBE_TRADING_ENABLE_INDMONEY", raising=False)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "missing.json",
    )
    out = _exec_holdings()
    assert out["error_kind"] == "needs_auth"
