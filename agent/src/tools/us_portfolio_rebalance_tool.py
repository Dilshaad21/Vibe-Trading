"""Deterministic, read-only US stock sleeve arithmetic for INDMoney."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from src.agent.tools import BaseTool
from src.integrations.indmoney import ErrorKind, build_error
from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool, gate_ok
from src.tools.path_utils import safe_document_path


def _amount(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def calculate_us_rebalance(
    snapshot: dict[str, Any],
    target_weights_pct: dict[str, float] | None = None,
    max_position_pct: float = 10.0,
) -> dict[str, Any]:
    """Analyze the US stock sleeve; apply optional *partial* target weights.

    Unspecified positions keep their current dollar value. Remaining value
    stays in the US stock wallet. This function does not choose targets or
    place orders.
    """
    if snapshot.get("currency") != "USD":
        raise ValueError("INDMoney holdings must be converted to USD for US sleeve analysis")
    if not isinstance(target_weights_pct, dict) and target_weights_pct is not None:
        raise ValueError("target_weights_pct must be a symbol-to-percent object")
    max_position_pct = _amount(max_position_pct, "max_position_pct")
    if max_position_pct > 100:
        raise ValueError("max_position_pct cannot exceed 100")

    rows = [h for h in snapshot.get("holdings", []) if h.get("asset_class") == "us_equity"]
    if not rows:
        raise ValueError("INDMoney returned no US equity holdings")
    wallet_rows = [
        row for row in snapshot.get("investments_by_asset_type", [])
        if row.get("asset_type") == "US_STOCK_WALLET"
    ]
    if len(wallet_rows) != 1:
        raise ValueError("Expected one US_STOCK_WALLET row in the INDMoney snapshot")
    wallet = _amount(wallet_rows[0].get("current_value"), "US stock wallet")

    positions: dict[str, dict[str, float]] = defaultdict(lambda: {"value": 0.0, "quantity": 0.0})
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("US equity holding is missing a symbol")
        if row.get("currency") != "USD":
            raise ValueError(f"{symbol} holding currency is not USD")
        positions[symbol]["value"] += _amount(row.get("market_value"), f"{symbol} market_value")
        positions[symbol]["quantity"] += _amount(row.get("quantity"), f"{symbol} quantity")

    stocks_value = sum(p["value"] for p in positions.values())
    sleeve_value = stocks_value + wallet
    if sleeve_value <= 0:
        raise ValueError("US stock sleeve has no current value")

    targets: dict[str, float] = {}
    for raw_symbol, raw_pct in (target_weights_pct or {}).items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or symbol in targets:
            raise ValueError("Target symbols must be non-empty and unique ignoring case")
        pct = _amount(raw_pct, f"{symbol} target weight")
        if pct > 100:
            raise ValueError(f"{symbol} target weight cannot exceed 100%")
        if symbol not in positions and pct > 0:
            raise ValueError(f"{symbol} is not a current holding; fetch a quote before sizing a new position")
        targets[symbol] = pct

    holdings = []
    trades = []
    net_buy = 0.0
    for symbol, position in sorted(positions.items(), key=lambda item: -item[1]["value"]):
        value, quantity = position["value"], position["quantity"]
        current_pct = value / sleeve_value * 100
        target_pct = targets.get(symbol)
        target_value = sleeve_value * target_pct / 100 if target_pct is not None else value
        delta = target_value - value
        unit_price = value / quantity if quantity > 0 else None
        holding = {
            "symbol": symbol,
            "quantity": round(quantity, 6),
            "market_value_usd": round(value, 2),
            "current_weight_pct": round(current_pct, 3),
            "implied_price_usd": round(unit_price, 4) if unit_price is not None else None,
            "over_max_position_pct": current_pct > max_position_pct,
        }
        if target_pct is not None:
            holding["target_weight_pct"] = target_pct
        holdings.append(holding)
        if target_pct is not None and abs(delta) >= 0.005:
            trades.append({
                "symbol": symbol,
                "side": "buy" if delta > 0 else "sell",
                "amount_usd": round(abs(delta), 2),
                "approx_shares": round(abs(delta) / unit_price, 6) if unit_price else None,
                "target_weight_pct": target_pct,
            })
            net_buy += delta

    remaining_wallet = wallet - net_buy
    top_five_value = sum(p["value"] for p in sorted(positions.values(), key=lambda p: -p["value"])[:5])
    result = {
        "ok": True,
        "currency": "USD",
        "source": "INDMoney",
        "snapshot_path": snapshot.get("snapshot_path"),
        "asof": snapshot.get("asof") or None,
        "from_cache": snapshot.get("from_cache"),
        "stock_count": len(positions),
        "stocks_value_usd": round(stocks_value, 2),
        "us_wallet_usd": round(wallet, 2),
        "sleeve_value_usd": round(sleeve_value, 2),
        "wallet_weight_pct": round(wallet / sleeve_value * 100, 3),
        "top_five_weight_pct": round(top_five_value / sleeve_value * 100, 3),
        "max_position_pct": max_position_pct,
        "holdings": holdings,
        "target_weights_are_partial": True,
        "trades": trades,
        "remaining_us_wallet_usd": round(remaining_wallet, 2),
        "remaining_us_wallet_pct": round(remaining_wallet / sleeve_value * 100, 3),
        "funding_gap_usd": round(max(0.0, -remaining_wallet), 2),
        "funded_by_wallet_and_sells": remaining_wallet >= -0.005,
        "execution": "analysis_only",
    }
    return result


class USPortfolioRebalanceTool(BaseTool):
    name = "us_portfolio_rebalance"
    description = (
        "Read INDMoney US stock holdings and US_STOCK_WALLET, compute sleeve weights, "
        "concentration, and optional trade sizes for caller-provided partial target weights. "
        "Unspecified holdings stay at current dollar value. Analysis only; no orders."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "force_refresh": {"type": "boolean", "default": False},
            "snapshot_path": {
                "type": "string",
                "description": "Optional path to a saved INDMoney holdings snapshot under an allowed indmoney uploads directory. Analyze that snapshot without claiming it is live.",
            },
            "target_weights_pct": {
                "type": "object",
                "additionalProperties": {"type": "number", "minimum": 0, "maximum": 100},
                "description": "Optional target percentages of the entire US stock-plus-wallet sleeve, keyed by existing symbol. Omitted positions are held at current dollar values.",
            },
            "max_position_pct": {"type": "number", "default": 10.0},
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        saved_path = kwargs.get("snapshot_path")
        if saved_path:
            if not gate_ok():
                return json.dumps(build_error(
                    ErrorKind.CONFIG_MISSING,
                    "Set VIBE_TRADING_ENABLE_INDMONEY=1 to enable INDMoney from a remote caller.",
                ))
            try:
                path = safe_document_path(str(saved_path))
                if path.parent.name != "indmoney" or "_holdings_" not in path.name or path.suffix != ".json":
                    raise ValueError("snapshot_path must be an INDMoney holdings snapshot")
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(snapshot, dict):
                    raise ValueError("snapshot_path does not contain a holdings object")
                snapshot["snapshot_path"] = str(path)
                snapshot["from_cache"] = True
                snapshot["snapshot_file_mtime_utc"] = datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return json.dumps({"ok": False, "error_kind": "invalid_snapshot_path", "message": str(exc)})
        else:
            try:
                snapshot = json.loads(IndMoneyHoldingsTool().execute(force_refresh=kwargs.get("force_refresh", False)))
            except httpx.HTTPError:
                return json.dumps({
                    "ok": False,
                    "error_kind": "upstream_unavailable",
                    "message": "INDMoney could not be reached; retry later or pass a saved holdings snapshot_path for labeled historical analysis.",
                })
        if not saved_path and not snapshot.get("ok"):
            return json.dumps(snapshot)
        try:
            result = calculate_us_rebalance(
                snapshot,
                target_weights_pct=kwargs.get("target_weights_pct"),
                max_position_pct=kwargs.get("max_position_pct", 10.0),
            )
        except ValueError as exc:
            return json.dumps({"ok": False, "error_kind": "invalid_input_or_snapshot", "message": str(exc)})
        if saved_path:
            result["snapshot_source"] = "saved_snapshot"
            result["snapshot_file_mtime_utc"] = snapshot["snapshot_file_mtime_utc"]
        else:
            result["snapshot_source"] = "indmoney_holdings"
        return json.dumps(result, allow_nan=False)
