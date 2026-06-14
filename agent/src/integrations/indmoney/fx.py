"""USD/INR FX lookup for converting INDMoney's INR-denominated values.

INDMoney's MCP returns every monetary value in INR — including US stock
prices (see ``normalizer`` and ``README``). To express holdings in USD we
divide INR amounts by the USD/INR spot rate (INR per 1 USD).

INDMoney exposes no FX rate, so the rate is fetched out-of-band from
Yahoo Finance (``USDINR=X``) via the same ``yfinance`` dependency the
backtest loaders already use. A short in-process cache avoids hammering
Yahoo on every holdings call, and an env override
(``INDMONEY_USDINR_RATE``) plus a static fallback keep conversion working
when the network is unavailable.
"""

from __future__ import annotations

import os
import time

# Fallback USD/INR rate (INR per USD) used only when both the env override
# and the live yfinance lookup are unavailable. Deliberately conservative
# and easy to spot as "stale" in output.
_FALLBACK_USDINR = 88.0

# In-process cache: (rate, fetched_at_monotonic).
_CACHE: tuple[float, float] | None = None
_CACHE_TTL_SECONDS = 900.0


def _env_rate() -> float | None:
    """Return the ``INDMONEY_USDINR_RATE`` override, or ``None`` if unset/invalid."""
    raw = os.environ.get("INDMONEY_USDINR_RATE")
    if raw is None or not raw.strip():
        return None
    try:
        rate = float(raw)
    except ValueError:
        return None
    return rate if rate > 0 else None


def _fetch_live_rate() -> float | None:
    """Fetch the latest USD/INR close from Yahoo Finance.

    Returns INR per 1 USD, or ``None`` if yfinance is unavailable or returns
    no usable data. Never raises — FX is best-effort.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker("USDINR=X")
        # fast_info is cheap and avoids a full history download.
        last = getattr(ticker, "fast_info", {}).get("last_price")
        if last and float(last) > 0:
            return float(last)

        hist = ticker.history(period="5d", interval="1d")
        if not hist.empty:
            close = float(hist["Close"].dropna().iloc[-1])
            if close > 0:
                return close
    except Exception as exc:  # pragma: no cover - network/extlib failure path
        print(f"[WARN] USD/INR yfinance lookup failed: {exc}")
    return None


def get_usdinr_rate(*, use_cache: bool = True) -> float:
    """Return the USD/INR rate (INR per 1 USD) used to convert INR -> USD.

    Resolution order:
      1. ``INDMONEY_USDINR_RATE`` env override (deterministic; for tests / pinning).
      2. Live yfinance ``USDINR=X`` lookup (cached for 15 minutes).
      3. Static fallback (:data:`_FALLBACK_USDINR`).

    Args:
        use_cache: When ``True`` (default), reuse a recently fetched live rate.

    Returns:
        A positive float; never raises.
    """
    override = _env_rate()
    if override is not None:
        return override

    global _CACHE
    if use_cache and _CACHE is not None:
        rate, fetched_at = _CACHE
        if (time.monotonic() - fetched_at) < _CACHE_TTL_SECONDS:
            return rate

    live = _fetch_live_rate()
    if live is not None:
        _CACHE = (live, time.monotonic())
        return live

    return _FALLBACK_USDINR
