"""Tests for the INDMoney USD/INR FX helper.

Network-free: we exercise the env override and the fallback path by
monkeypatching the live lookup. The live yfinance path itself is not
unit-tested (it would hit the network).
"""

from __future__ import annotations

import src.integrations.indmoney.fx as fx


def _clear_cache():
    fx._CACHE = None


def test_env_override_takes_precedence(monkeypatch):
    _clear_cache()
    monkeypatch.setenv("INDMONEY_USDINR_RATE", "83.5")
    # Even if a live rate would be available, the override wins.
    monkeypatch.setattr(fx, "_fetch_live_rate", lambda: 999.0)
    assert fx.get_usdinr_rate() == 83.5


def test_invalid_env_override_is_ignored(monkeypatch):
    _clear_cache()
    monkeypatch.setenv("INDMONEY_USDINR_RATE", "not-a-number")
    monkeypatch.setattr(fx, "_fetch_live_rate", lambda: 90.0)
    assert fx.get_usdinr_rate() == 90.0


def test_nonpositive_env_override_is_ignored(monkeypatch):
    _clear_cache()
    monkeypatch.setenv("INDMONEY_USDINR_RATE", "0")
    monkeypatch.setattr(fx, "_fetch_live_rate", lambda: 87.0)
    assert fx.get_usdinr_rate() == 87.0


def test_falls_back_when_live_lookup_unavailable(monkeypatch):
    _clear_cache()
    monkeypatch.delenv("INDMONEY_USDINR_RATE", raising=False)
    monkeypatch.setattr(fx, "_fetch_live_rate", lambda: None)
    assert fx.get_usdinr_rate() == fx._FALLBACK_USDINR


def test_live_rate_is_cached(monkeypatch):
    _clear_cache()
    monkeypatch.delenv("INDMONEY_USDINR_RATE", raising=False)
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        return 84.0

    monkeypatch.setattr(fx, "_fetch_live_rate", _flaky)
    first = fx.get_usdinr_rate()
    second = fx.get_usdinr_rate()
    assert first == second == 84.0
    assert calls["n"] == 1, "second call should hit the in-process cache"
