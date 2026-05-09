"""Pull a current macro snapshot — central-bank rates, yields, FX,
commodities — from public sources. No API keys required.

The fetcher is partial-failure-tolerant: if one source fails, the
corresponding field becomes ``None`` and an entry lands in the
top-level ``_errors`` list. The tool layer surfaces ``_errors`` to
the caller so the agent can decide whether to proceed.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Mapping: snapshot field name → (group, source_kind, source_id)
# Order matters only for deterministic _sources output.
_FIELDS: list[tuple[str, str, str, str]] = [
    # group, field, kind, id
    ("central_bank_rates", "fed_funds_target_upper", "FRED", "DFEDTARU"),
    ("central_bank_rates", "fed_funds_target_lower", "FRED", "DFEDTARL"),
    ("central_bank_rates", "ecb_deposit",            "FRED", "ECBDFR"),
    ("central_bank_rates", "boe_bank_rate",          "FRED", "IUDSOIA"),
    # NB: RBI repo and BoJ policy rates are not consistently available on
    # FRED. They are intentionally omitted from v1 — Claude Code can fall
    # back to web_search() in the recipe step.
    ("yields", "ust_2y",  "FRED", "DGS2"),
    ("yields", "ust_10y", "FRED", "DGS10"),
    ("yields", "ust_30y", "FRED", "DGS30"),
    ("fx", "usd_inr",  "yfinance", "INR=X"),
    ("fx", "dxy",      "yfinance", "DX-Y.NYB"),
    ("fx", "eur_usd",  "yfinance", "EURUSD=X"),
    ("fx", "usd_jpy",  "yfinance", "JPY=X"),
    ("commodities", "brent_usd",  "yfinance", "BZ=F"),
    ("commodities", "wti_usd",    "yfinance", "CL=F"),
    ("commodities", "gold_usd_oz", "yfinance", "GC=F"),
]


def _safe_float(value: Any) -> float | None:
    """Convert to float and reject NaN. Used to guard yfinance NaN responses."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def fetch_macro_snapshot(
    *,
    fred_getter: Callable[[str], float] | None = None,
    yf_getter: Callable[[str], float] | None = None,
) -> dict[str, Any]:
    """Build the full macro snapshot.

    Args:
        fred_getter: Callable taking a FRED series id and returning the
            latest float observation. Defaults to the live HTTP getter.
        yf_getter: Callable taking a yfinance ticker and returning the
            latest float close. Defaults to the live yfinance getter.

    Returns:
        A dict with the shape documented in the spec
        (docs/superpowers/specs/2026-05-09-mcp-llm-boundary-design.md §4).
    """
    if fred_getter is None:
        from src.integrations.macro.sources import fred_csv_latest
        fred_getter = fred_csv_latest
    if yf_getter is None:
        from src.integrations.macro.sources import yfinance_latest
        yf_getter = yfinance_latest

    out: dict[str, Any] = {
        "asof": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "central_bank_rates": {},
        "yields": {},
        "fx": {},
        "commodities": {},
        "_sources": {},
        "_errors": [],
    }

    for group, field, kind, source_id in _FIELDS:
        try:
            if kind == "FRED":
                raw = fred_getter(source_id)
            elif kind == "yfinance":
                raw = yf_getter(source_id)
            else:
                raise RuntimeError(f"unknown source kind {kind!r}")
            value = _safe_float(raw)
            if value is None:
                out[group][field] = None
                out["_errors"].append({
                    "field": field, "source": f"{kind}:{source_id}",
                    "reason": "non-numeric / NaN response",
                })
            else:
                out[group][field] = value
        except Exception as exc:
            out[group][field] = None
            out["_errors"].append({
                "field": field, "source": f"{kind}:{source_id}",
                "reason": str(exc),
            })
        out["_sources"][field] = f"{kind}:{source_id}"

    # Computed: 2s10s spread in basis points (10y - 2y) * 100, when both present.
    y2 = out["yields"].get("ust_2y")
    y10 = out["yields"].get("ust_10y")
    out["yields"]["us_2s10s_bp"] = round((y10 - y2) * 100) if (y2 is not None and y10 is not None) else None

    return out
