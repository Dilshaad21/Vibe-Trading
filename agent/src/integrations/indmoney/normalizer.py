"""Normalize INDMoney MCP responses into Vibe-Trading internal types.

Maps the real ``networth_*`` tool surface (per the post-OAuth discovery
notes) into our ``Holding`` dataclass and a plain-dict snapshot view.
INDMoney's MCP returns all monetary values in INR — including US stock
prices — so ``Holding.currency`` is always ``"INR"`` from this source.
"""

from __future__ import annotations

from typing import Any

from src.integrations.indmoney.types import Holding

_ASSET_TYPE_TO_CLASS = {
    "US_STOCK": "us_equity",
    "IND_STOCK": "indian_equity",
    "MF": "mf",
}


def _to_float(value: Any, *, default: float = 0.0) -> float:
    """Coerce a JSON value to ``float`` defensively.

    INDMoney returns the literal string ``"unknown"`` in some monetary
    fields (e.g. ``invested_amount`` for legacy / corporate-action positions
    where the cost basis is not known). It also occasionally returns
    ``None``. Both must coerce to ``default`` rather than raising.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _classify_v2(asset_type: str) -> str:
    """Map an INDMoney ``asset_type`` enum value to our ``Holding.asset_class``.

    Falls back to ``"other"`` for asset_types we haven't catalogued (BOND,
    EPF, NPS, SA, FD, CRYPTO, INSURANCE, VEHICLE, RE, RD, AIF, PMS, PPF).
    Downstream analytics that filter on asset_class still work; the
    untagged buckets simply won't roll up into US/Indian/MF aggregates.
    """
    return _ASSET_TYPE_TO_CLASS.get(asset_type, "other")


def normalize_networth_holdings(asset_type: str, payload: dict[str, Any]) -> list[Holding]:
    """Convert an INDMoney ``networth_holdings(asset_type=...)`` response.

    Per spec section 6 (post-discovery), every value INDMoney returns is in
    INR — including US stock prices — so ``Holding.currency`` is always
    ``"INR"`` from this source.

    ``Holding.symbol`` is set to INDMoney's ``investment_code`` (e.g. "112192").
    Mapping that to a ticker symbol (AAPL, DOCN) is a separate concern; users
    that need ticker-based market-data lookups should pair this with the
    ``lookup_ind_keys`` tool or maintain their own mapping.
    """
    out: list[Holding] = []
    for h in payload.get("holdings", []) or []:
        units = _to_float(h.get("total_units"))
        invested = _to_float(h.get("invested_amount"))
        avg_cost = invested / units if units else 0.0
        out.append(Holding(
            symbol=str(h.get("investment_code", "")),
            name=str(h.get("investment", "")),
            quantity=units,
            avg_cost=avg_cost,
            market_value=_to_float(h.get("market_value")),
            unrealized_pnl=_to_float(h.get("total_pnl")),
            currency="INR",
            asset_class=_classify_v2(asset_type),
            asof="",  # networth_holdings is point-in-time; no asof field returned
        ))
    return out


def normalize_networth_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert an INDMoney ``networth_snapshot`` response into a plain dict.

    Keeps the upstream structure (``investments`` per asset_type,
    ``assets`` per assetclass_l2, ``sector`` per sector) so downstream
    callers can pivot freely. Coerces top-level totals to floats and
    defaults missing arrays to empty.
    """
    return {
        "total_invested": _to_float(payload.get("total_invested")),
        "total_current_value": _to_float(payload.get("total_current_value")),
        "total_networth": _to_float(payload.get("total_networth")),
        "investments": list(payload.get("investments") or []),
        "assets": list(payload.get("assets") or []),
        "sector": list(payload.get("sector") or []),
    }
