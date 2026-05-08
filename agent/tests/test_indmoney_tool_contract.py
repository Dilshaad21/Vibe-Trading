"""End-to-end contract tests for the three INDMoney tools.

Uses httpx.MockTransport to simulate the MCP server. Verifies the JSON
envelope shape from each tool under happy and error paths.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect uploads root + token path + client-credentials path to tmp."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "token.json",
    )
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_CLIENT_PATH",
        tmp_path / "client.json",
    )
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(Token(
        access_token="acc", refresh_token="ref",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))
    (tmp_path / "client.json").write_text(json.dumps({
        "client_id": "cid_test",
        "client_secret": "csec_test",
    }))


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
        "networth_snapshot": {
            "total_invested": 100.0, "total_current_value": 200.0,
            "total_networth": 200.0,
            "investments": [
                {"asset_type": "US_STOCK", "current_value": 200.0, "invested_value": 100.0},
            ],
            "assets": [
                {"assetclass_l2": "Liquid", "current_value": 50.0, "invested_value": 50.0},
            ],
            "sector": [],
        },
        "networth_holdings": {
            "holdings": [{
                "investment_code": "100001", "investment": "Example US Equity",
                "asset_type": "US_STOCK", "assetclass_l2": "Global Equity",
                "invested_amount": 100.0, "market_value": 200.0,
                "total_pnl": 100.0, "total_units": 1.0, "unit_price": 200.0,
            }],
        },
    })
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    _patch_httpx_client(monkeypatch, transport)
    monkeypatch.setenv("INDMONEY_ASSET_TYPES", "US_STOCK")
    out = json.loads(IndMoneyHoldingsTool().execute(force_refresh=True))
    assert out["ok"] is True
    # Symbol = INDMoney's investment_code (no ticker resolution in v1).
    assert out["holdings"][0]["symbol"] == "100001"
    assert out["holdings"][0]["currency"] == "INR"
    # Liquid assetclass surfaces as cash_inr; cash_usd is always 0 from this MCP.
    assert out["cash"]["cash_inr"] == 50.0
    assert out["cash"]["cash_usd"] == 0.0
    assert out["totals"]["total_current_value"] == 200.0
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


def test_sync_tool_returns_aggregate_status(monkeypatch, tmp_path):
    transport = _stub_transport({
        "networth_snapshot": {
            "total_invested": 0, "total_current_value": 0, "total_networth": 0,
            "investments": [], "assets": [], "sector": [],
        },
        "networth_holdings": {"holdings": []},
    })
    from src.tools.indmoney_sync_tool import IndMoneySyncTool
    _patch_httpx_client(monkeypatch, transport)
    monkeypatch.setenv("INDMONEY_ASSET_TYPES", "US_STOCK")
    out = json.loads(IndMoneySyncTool().execute())
    assert out["ok"] is True
    assert out["status"] == "ok"
    assert out["holdings_count"] == 0
    # The transactions piece was dropped in v2 — INDMoney has no MCP
    # transaction stream — so the envelope no longer carries a count.
    assert "transactions_count" not in out


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
