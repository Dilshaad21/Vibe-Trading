"""Normalize INDMoney MCP responses into Vibe-Trading internal types.

Maps the real ``networth_*`` tool surface (per the post-OAuth discovery
notes) into our ``Holding`` dataclass and a plain-dict snapshot view.
INDMoney's MCP returns all monetary values in INR — including US stock
prices. Values are preserved as INR by default; pass an ``fx_rate`` (INR
per 1 USD, e.g. from :mod:`src.integrations.indmoney.fx`) to convert the
monetary fields to USD, in which case ``currency`` becomes ``"USD"``.
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


def normalize_networth_holdings(
    asset_type: str,
    payload: dict[str, Any],
    *,
    fx_rate: float | None = None,
) -> list[Holding]:
    """Convert an INDMoney ``networth_holdings(asset_type=...)`` response.

    Per spec section 6 (post-discovery), every value INDMoney returns is in
    INR — including US stock prices. By default this function preserves those
    raw INR values and tags ``Holding.currency = "INR"``.

    Pass ``fx_rate`` (INR per 1 USD, e.g. from
    :func:`src.integrations.indmoney.fx.get_usdinr_rate`) to convert the
    monetary fields (``avg_cost``, ``market_value``, ``unrealized_pnl``) into
    USD; ``Holding.currency`` then becomes ``"USD"``. ``quantity`` is unitless
    and never scaled.

    ``Holding.symbol`` is set to INDMoney's ``investment_code`` (e.g. "112192").
    Mapping that to a ticker symbol (AAPL, DOCN) is a separate concern; users
    that need ticker-based market-data lookups should pair this with the
    ``lookup_ind_keys`` tool or maintain their own mapping.
    """
    convert = fx_rate is not None and fx_rate > 0
    currency = "USD" if convert else "INR"

    def _conv(value: float) -> float:
        return value / fx_rate if convert else value

    out: list[Holding] = []
    for h in payload.get("holdings", []) or []:
        units = _to_float(h.get("total_units"))
        invested = _to_float(h.get("invested_amount"))
        avg_cost = invested / units if units else 0.0
        out.append(Holding(
            symbol=str(h.get("investment_code", "")),
            name=str(h.get("investment", "")),
            quantity=units,
            avg_cost=_conv(avg_cost),
            market_value=_conv(_to_float(h.get("market_value"))),
            unrealized_pnl=_conv(_to_float(h.get("total_pnl"))),
            currency=currency,
            asset_class=_classify_v2(asset_type),
            asof="",  # networth_holdings is point-in-time; no asof field returned
        ))
    return out


# Monetary keys inside the snapshot's nested breakdown rows (``investments``,
# ``assets``, ``sector``, ``market_cap``). ``*_percentage`` / ``progress_*``
# fields are ratios and must NOT be scaled by FX.
_SNAPSHOT_MONEY_KEYS = ("invested_value", "current_value", "return")


def _convert_rows(rows: list[dict[str, Any]], fx_rate: float) -> list[dict[str, Any]]:
    """Return copies of ``rows`` with INR money fields divided by ``fx_rate``."""
    converted: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        for key in _SNAPSHOT_MONEY_KEYS:
            if key in new_row:
                new_row[key] = _to_float(new_row[key]) / fx_rate
        converted.append(new_row)
    return converted


def normalize_networth_snapshot(
    payload: dict[str, Any],
    *,
    fx_rate: float | None = None,
) -> dict[str, Any]:
    """Convert an INDMoney ``networth_snapshot`` response into a plain dict.

    Keeps the upstream structure (``investments`` per asset_type,
    ``assets`` per assetclass_l2, ``sector`` per sector) so downstream
    callers can pivot freely. Coerces top-level totals to floats and
    defaults missing arrays to empty.

    Values are INR by default. Pass ``fx_rate`` (INR per 1 USD) to convert the
    top-level totals and every nested money field (``invested_value``,
    ``current_value``, ``return``) into USD; percentage/ratio fields are left
    untouched. The output ``currency`` key records which applies.
    """
    convert = fx_rate is not None and fx_rate > 0
    scale = (lambda v: _to_float(v) / fx_rate) if convert else _to_float

    investments = list(payload.get("investments") or [])
    assets = list(payload.get("assets") or [])
    sector = list(payload.get("sector") or [])
    if convert:
        investments = _convert_rows(investments, fx_rate)
        assets = _convert_rows(assets, fx_rate)
        sector = _convert_rows(sector, fx_rate)

    return {
        "currency": "USD" if convert else "INR",
        "total_invested": scale(payload.get("total_invested")),
        "total_current_value": scale(payload.get("total_current_value")),
        "total_networth": scale(payload.get("total_networth")),
        "investments": investments,
        "assets": assets,
        "sector": sector,
    }
