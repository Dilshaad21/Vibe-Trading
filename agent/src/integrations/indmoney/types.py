"""Public dataclasses for INDMoney integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Holding:
    """A single open position or cash-equivalent line.

    Attributes:
        symbol: Bare ticker for US equities ("AAPL"); exchange-qualified for
            non-US (".NS" / ".BO" for Indian; etc.).
        name: Human-readable instrument name.
        quantity: Filled quantity (fractional shares supported).
        avg_cost: Cost basis per unit, in ``currency`` (NOT silently
            FX-converted).
        market_value: Current value at fetch time, in ``currency``.
        unrealized_pnl: market_value - quantity*avg_cost, in ``currency``.
        currency: ISO-4217 code ("USD" / "INR").
        asset_class: One of "us_equity" | "us_etf" | "indian_equity" | "mf".
        asof: ISO8601 timestamp from the source.
    """

    symbol: str
    name: str
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    currency: str
    asset_class: str
    asof: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Holding":
        return cls(**d)


@dataclass(frozen=True)
class CashSnapshot:
    """Account-level cash, native + FX."""

    cash_usd: float
    cash_inr: float
    pending_settlement_usd: float
    asof: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CashSnapshot":
        return cls(**d)
