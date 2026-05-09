"""Tests for the macro snapshot fetcher (pure, no network)."""

from __future__ import annotations


def test_fetch_macro_snapshot_happy_path():
    """All sources return; output has every expected field populated and no errors."""
    from src.integrations.macro.snapshot import fetch_macro_snapshot

    fred_calls: list[str] = []
    yf_calls: list[str] = []

    def fake_fred(series_id: str) -> float:
        fred_calls.append(series_id)
        return {
            "DFEDTARU": 5.50, "DFEDTARL": 5.25, "ECBDFR": 4.00,
            "IUDSOIA": 5.20, "DGS2": 4.81, "DGS10": 4.34, "DGS30": 4.52,
        }[series_id]

    def fake_yf(ticker: str) -> float:
        yf_calls.append(ticker)
        return {
            "INR=X": 83.45, "DX-Y.NYB": 104.21,
            "EURUSD=X": 1.08, "JPY=X": 152.30,
            "BZ=F": 84.20, "CL=F": 80.05, "GC=F": 2310.50,
            "^TNX": 4.34,
        }[ticker]

    snap = fetch_macro_snapshot(fred_getter=fake_fred, yf_getter=fake_yf)

    # Top-level structure
    assert "asof" in snap
    assert "central_bank_rates" in snap
    assert "yields" in snap
    assert "fx" in snap
    assert "commodities" in snap
    assert snap["_errors"] == []

    # Spot-check a few fields
    assert snap["central_bank_rates"]["fed_funds_target_upper"] == 5.50
    assert snap["central_bank_rates"]["fed_funds_target_lower"] == 5.25
    assert snap["central_bank_rates"]["ecb_deposit"] == 4.00
    assert snap["yields"]["ust_2y"] == 4.81
    assert snap["yields"]["ust_10y"] == 4.34
    assert snap["yields"]["us_2s10s_bp"] == round((4.34 - 4.81) * 100)
    assert snap["fx"]["usd_inr"] == 83.45
    assert snap["commodities"]["gold_usd_oz"] == 2310.50

    # Provenance recorded
    assert "fed_funds_target_upper" in snap["_sources"]
    assert snap["_sources"]["ust_10y"].startswith("FRED:")


def test_fetch_macro_snapshot_partial_failure_records_errors():
    """If FRED 503s for one series and yfinance returns NaN for another,
    the snapshot still returns; failed fields are null and _errors lists them."""
    from src.integrations.macro.snapshot import fetch_macro_snapshot

    def flaky_fred(series_id: str) -> float:
        if series_id == "ECBDFR":
            raise RuntimeError("FRED 503")
        return 5.50

    def flaky_yf(ticker: str) -> float:
        if ticker == "INR=X":
            return float("nan")  # yfinance returns NaN on missing
        return 100.0

    snap = fetch_macro_snapshot(fred_getter=flaky_fred, yf_getter=flaky_yf)

    # Failed fields are null, not omitted
    assert snap["central_bank_rates"]["ecb_deposit"] is None
    assert snap["fx"]["usd_inr"] is None

    # Successful fields still populated
    assert snap["central_bank_rates"]["fed_funds_target_upper"] == 5.50
    assert snap["fx"]["dxy"] == 100.0

    # Errors are surfaced
    err_fields = {e["field"] for e in snap["_errors"]}
    assert "ecb_deposit" in err_fields
    assert "usd_inr" in err_fields
    assert "FRED 503" in next(e for e in snap["_errors"] if e["field"] == "ecb_deposit")["reason"]


def test_fetch_macro_snapshot_2s10s_handles_null():
    """If either UST 2Y or 10Y is null, us_2s10s_bp must be null too."""
    from src.integrations.macro.snapshot import fetch_macro_snapshot

    def fred_missing_2y(series_id: str) -> float:
        if series_id == "DGS2":
            raise RuntimeError("not available")
        return 4.34  # everything else

    snap = fetch_macro_snapshot(
        fred_getter=fred_missing_2y, yf_getter=lambda t: 100.0,
    )

    assert snap["yields"]["ust_2y"] is None
    assert snap["yields"]["ust_10y"] == 4.34
    assert snap["yields"]["us_2s10s_bp"] is None
