"""End-to-end contract tests for the three INDMoney tools.

Uses httpx.MockTransport to simulate the MCP server. Verifies the JSON
envelope shape from each tool under happy and error paths.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect uploads root + token path to a tmp dir."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "token.json",
    )
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(Token(
        access_token="acc", refresh_token="ref",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))


def _stub_transport(responses: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = body.get("params", {}).get("name", "")
        payload = responses.get(name, {})
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": payload}]},
        })
    return httpx.MockTransport(handler)


def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Patch httpx.Client to return a client wired to the mock transport.

    We subclass instead of using a lambda because openai (imported transitively
    by the agent stack) does ``class _DefaultHttpxClient(httpx.Client): ...``
    at module load — a lambda would break that subclass relationship.
    """
    real_client = httpx.Client

    class _StubClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _StubClient)


def test_holdings_tool_happy_path(monkeypatch, tmp_path):
    transport = _stub_transport({
        "get_holdings": {"asof": "2026-05-07T14:30:00+05:30",
                          "positions": [{"symbol": "AAPL", "name": "Apple",
                                         "quantity": 1, "avg_cost": 1, "market_value": 2,
                                         "unrealized_pnl": 1, "currency": "USD",
                                         "instrument_type": "equity"}]},
        "get_account": {"asof": "2026-05-07T14:30:00+05:30",
                         "cash_usd": 100.0, "cash_inr": 0, "pending_settlement_usd": 0},
    })
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    _patch_httpx_client(monkeypatch, transport)
    out = json.loads(IndMoneyHoldingsTool().execute(force_refresh=True))
    assert out["ok"] is True
    assert out["holdings"][0]["symbol"] == "AAPL"
    assert out["cash"]["cash_usd"] == 100.0
    assert "snapshot_path" in out


def test_holdings_tool_needs_auth_when_no_token(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "absent.json",
    )
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = json.loads(IndMoneyHoldingsTool().execute())
    assert out["ok"] is False
    assert out["error_kind"] == "needs_auth"


def test_transactions_tool_writes_both_csvs(monkeypatch, tmp_path):
    transport = _stub_transport({
        "get_transactions": {
            "items": [
                {"datetime": "2026-04-01", "symbol": "AAPL", "name": "Apple",
                 "type": "buy", "quantity": 1, "price": 150.0, "amount": 150.0,
                 "fee": 0.0, "currency": "USD"},
                {"datetime": "2026-04-02", "symbol": "AAPL", "name": "Apple",
                 "type": "dividend", "quantity": 0, "price": 0.0, "amount": 0.5,
                 "fee": 0.0, "currency": "USD"},
            ]
        }
    })
    from src.tools.indmoney_transactions_tool import IndMoneyTransactionsTool
    _patch_httpx_client(monkeypatch, transport)
    out = json.loads(IndMoneyTransactionsTool().execute(
        start_date="2026-04-01", end_date="2026-04-30", force_refresh=True))
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["events_count"] == 1
    assert Path(out["csv_path"]).exists()
    assert Path(out["events_csv_path"]).exists()


def test_sync_tool_returns_aggregate_status(monkeypatch, tmp_path):
    transport = _stub_transport({
        "get_holdings":     {"asof": "2026-05-07", "positions": []},
        "get_account":      {"asof": "2026-05-07", "cash_usd": 0, "cash_inr": 0, "pending_settlement_usd": 0},
        "get_transactions": {"items": []},
    })
    from src.tools.indmoney_sync_tool import IndMoneySyncTool
    _patch_httpx_client(monkeypatch, transport)
    out = json.loads(IndMoneySyncTool().execute())
    assert out["ok"] is True
    assert out["status"] == "ok"
    assert out["holdings_count"] == 0
    assert out["transactions_count"] == 0


def test_sync_tool_needs_auth_returns_auth_url(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "absent.json",
    )
    from src.tools.indmoney_sync_tool import IndMoneySyncTool
    out = json.loads(IndMoneySyncTool().execute())
    assert out["ok"] is False
    assert out["error_kind"] == "needs_auth"
    assert "auth_url" in out
