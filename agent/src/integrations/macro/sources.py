"""Network-touching getters for macro_snapshot.

Each getter is a thin function that takes a single string identifier
(FRED series id / yfinance ticker) and returns a float, or raises
RuntimeError. The orchestrator in snapshot.py injects them so unit tests
can stub the network entirely.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pandas as pd

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def fred_csv_latest(series_id: str, *, timeout: float = 15.0) -> float:
    """Fetch the most recent observation of a FRED series via the public
    CSV endpoint. No API key required.

    The CSV format is two columns: ``observation_date,<SERIES_ID>``. We
    pull the last row that has a numeric value (FRED uses ``.`` for missing).

    Raises:
        RuntimeError: HTTP failure, no numeric rows, or parse error.
    """
    url = _FRED_CSV_URL.format(series=series_id)
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    except Exception as exc:
        raise RuntimeError(f"FRED HTTP error for {series_id}: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"FRED HTTP {resp.status_code} for {series_id}")
    try:
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as exc:
        raise RuntimeError(f"FRED CSV parse failed for {series_id}: {exc}") from exc
    if df.empty or series_id not in df.columns:
        raise RuntimeError(f"FRED CSV missing series column for {series_id}")
    series = pd.to_numeric(df[series_id], errors="coerce").dropna()
    if series.empty:
        raise RuntimeError(f"FRED series {series_id} has no numeric observations")
    return float(series.iloc[-1])


def yfinance_latest(ticker: str) -> float:
    """Fetch the most recent close for a yfinance ticker.

    Wraps ``yfinance.Ticker(...).history(period='5d')`` (5d gives buffer
    against weekend/holiday gaps). Returns the last non-NaN close.

    Raises:
        RuntimeError: yfinance error or no usable rows.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(f"yfinance not installed: {exc}") from exc
    try:
        hist = yf.Ticker(ticker).history(period="5d")
    except Exception as exc:
        raise RuntimeError(f"yfinance error for {ticker}: {exc}") from exc
    if hist.empty or "Close" not in hist.columns:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    closes = hist["Close"].dropna()
    if closes.empty:
        raise RuntimeError(f"yfinance returned only NaN closes for {ticker}")
    return float(closes.iloc[-1])
