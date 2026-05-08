"""Normalize INDMoney MCP responses into Vibe-Trading internal types.

The trades CSV uses the column shape consumed by
``src.tools.trade_journal_parsers.parse_generic``. Per spec Section 5,
non-trade events (dividends, splits, unknown types) are emitted to a
separate events CSV — they MUST NOT enter the trades CSV because
``_normalize_side`` collapses any non-buy/sell value to "buy", which
would corrupt FIFO PnL pairing.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from src.integrations.indmoney.types import CashSnapshot, Holding
from src.tools.trade_journal_parsers import TradeRecord

logger = logging.getLogger(__name__)

_TRADE_TYPES = {"buy", "sell"}
_KNOWN_EVENT_TYPES = {"dividend", "split", "merger", "spinoff", "reverse_split"}

_INDIAN_SUFFIXES = (".NS", ".BO")


def _classify_asset(symbol: str, instrument_type: str) -> str:
    """Map (symbol, instrument_type) → asset_class enum value."""
    s = symbol.upper()
    t = (instrument_type or "").lower()
    if any(s.endswith(suf) for suf in _INDIAN_SUFFIXES):
        return "indian_equity"
    if t == "etf":
        return "us_etf"
    if t in {"mutual_fund", "mf"}:
        return "mf"
    return "us_equity"


def _market_for(symbol: str) -> str:
    """Map symbol → existing TradeRecord market bucket."""
    s = symbol.upper()
    if any(s.endswith(suf) for suf in _INDIAN_SUFFIXES):
        return "other"  # Indian equities not yet a first-class market
    return "us"


def normalize_holdings(payload: dict[str, Any]) -> list[Holding]:
    """Convert an INDMoney holdings response into ``Holding`` objects."""
    asof = str(payload.get("asof", ""))
    out: list[Holding] = []
    for p in payload.get("positions", []):
        out.append(Holding(
            symbol=str(p["symbol"]).upper(),
            name=str(p.get("name", "")),
            quantity=float(p["quantity"]),
            avg_cost=float(p["avg_cost"]),
            market_value=float(p["market_value"]),
            unrealized_pnl=float(p.get("unrealized_pnl", 0.0)),
            currency=str(p.get("currency", "USD")),
            asset_class=_classify_asset(str(p["symbol"]), str(p.get("instrument_type", ""))),
            asof=asof,
        ))
    return out


def normalize_cash(payload: dict[str, Any]) -> CashSnapshot:
    """Convert an INDMoney cash response into a ``CashSnapshot``."""
    return CashSnapshot(
        cash_usd=float(payload.get("cash_usd", 0.0)),
        cash_inr=float(payload.get("cash_inr", 0.0)),
        pending_settlement_usd=float(payload.get("pending_settlement_usd", 0.0)),
        asof=str(payload.get("asof", "")),
    )


def normalize_transactions(
    payload: dict[str, Any],
) -> tuple[list[TradeRecord], list[dict[str, Any]]]:
    """Split an INDMoney transactions response into trades + events.

    Trades go to the FIFO-eligible CSV (only side="buy"|"sell"). Everything
    else (dividends, splits, unknown types) lands in the events list.
    Unknown event types are preserved with the raw payload in ``notes``.
    """
    trades: list[TradeRecord] = []
    events: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        kind = str(item.get("type", "")).lower()
        symbol = str(item.get("symbol", "")).upper()
        dt = str(item.get("datetime", ""))
        currency = str(item.get("currency", "USD"))

        if kind in _TRADE_TYPES:
            fx = item.get("fx_usd_inr")
            name = str(item.get("name", ""))
            if fx is not None:
                name = f"{name} (fx_usd_inr={fx})"
            trades.append(TradeRecord(
                datetime=dt,
                symbol=symbol,
                name=name,
                side=kind,
                quantity=float(item.get("quantity", 0.0)),
                price=float(item.get("price", 0.0)),
                amount=float(item.get("amount", 0.0)),
                fee=float(item.get("fee", 0.0)),
                market=_market_for(symbol),
            ))
            continue

        event_type = kind if kind in _KNOWN_EVENT_TYPES else "unknown"
        if event_type == "unknown":
            logger.warning("indmoney: unknown transaction type %r — emitting to events CSV", kind)
        events.append({
            "datetime": dt,
            "symbol": symbol,
            "event_type": event_type,
            "quantity_delta": float(item.get("quantity", 0.0)),
            "cash_delta": float(item.get("amount", 0.0)),
            "ratio": str(item.get("ratio", "")),
            "currency": currency,
            "notes": "" if event_type != "unknown" else f"raw_type={kind}; raw={item!r}",
        })
    return trades, events


_TRADES_HEADER = ["datetime", "symbol", "name", "side",
                  "quantity", "price", "amount", "fee", "market"]

_EVENTS_HEADER = ["datetime", "symbol", "event_type", "quantity_delta",
                  "cash_delta", "ratio", "currency", "notes"]


def write_trades_csv(trades: list[TradeRecord], path: Path) -> None:
    """Write trades to a generic-format CSV consumable by parse_generic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_TRADES_HEADER)
        for t in trades:
            w.writerow([t.datetime, t.symbol, t.name, t.side,
                        t.quantity, t.price, t.amount, t.fee, t.market])


# ---------- v2: real INDMoney networth payloads ----------

_ASSET_TYPE_TO_CLASS = {
    "US_STOCK": "us_equity",
    "IND_STOCK": "indian_equity",
    "MF": "mf",
}


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
    INR — including US stock prices (Seagate at ₹72,227/unit, etc.) — so
    ``Holding.currency`` is always ``"INR"`` from this source.

    ``Holding.symbol`` is set to INDMoney's ``investment_code`` (e.g. "112192").
    Mapping that to a ticker symbol (AAPL, DOCN) is a separate concern; users
    that need ticker-based market-data lookups should pair this with the
    ``lookup_ind_keys`` tool or maintain their own mapping.
    """
    out: list[Holding] = []
    for h in payload.get("holdings", []) or []:
        units = float(h.get("total_units", 0) or 0)
        invested = float(h.get("invested_amount", 0) or 0)
        avg_cost = invested / units if units else 0.0
        out.append(Holding(
            symbol=str(h.get("investment_code", "")),
            name=str(h.get("investment", "")),
            quantity=units,
            avg_cost=avg_cost,
            market_value=float(h.get("market_value", 0) or 0),
            unrealized_pnl=float(h.get("total_pnl", 0) or 0),
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
        "total_invested": float(payload.get("total_invested", 0) or 0),
        "total_current_value": float(payload.get("total_current_value", 0) or 0),
        "total_networth": float(payload.get("total_networth", 0) or 0),
        "investments": list(payload.get("investments") or []),
        "assets": list(payload.get("assets") or []),
        "sector": list(payload.get("sector") or []),
    }


def write_events_csv(events: list[dict[str, Any]], path: Path) -> None:
    """Write events (dividends, splits, unknowns) to a sibling CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_EVENTS_HEADER)
        for e in events:
            w.writerow([e["datetime"], e["symbol"], e["event_type"],
                        e["quantity_delta"], e["cash_delta"],
                        e["ratio"], e["currency"], e["notes"]])
