"""Verify tokens never leak into tool output, audit logs, or tracebacks."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "token.json",
    )
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_CLIENT_PATH",
        tmp_path / "client.json",
    )
    TokenCache(path=tmp_path / "token.json").save(Token(
        access_token="SECRET-DO-NOT-LEAK",
        refresh_token="REFRESH-DO-NOT-LEAK",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))
    (tmp_path / "client.json").write_text(json.dumps({
        "client_id": "cid_test",
        "client_secret": "csec_test",
    }))


def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Match the helper used in test_indmoney_tool_contract.py."""
    real_client = httpx.Client

    class _StubClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _StubClient)


def test_holdings_tool_output_excludes_token(monkeypatch):
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "json", "json": {"asof": "x", "positions": []}}]},
    }))
    _patch_httpx_client(monkeypatch, transport)
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = IndMoneyHoldingsTool().execute(force_refresh=True)
    assert "SECRET-DO-NOT-LEAK" not in out
    assert "REFRESH-DO-NOT-LEAK" not in out


def test_audit_log_redacts_tokens(tmp_path):
    from src.integrations.indmoney.audit import append_audit
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="x", outcome="err",
                 detail="GET / 401 — Authorization: Bearer SECRET-DO-NOT-LEAK")
    assert "SECRET-DO-NOT-LEAK" not in log.read_text()


def test_tool_error_envelope_does_not_include_token(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if "/oauth/token" in str(req.url):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(401)
    transport = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, transport)
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = IndMoneyHoldingsTool().execute(force_refresh=True)
    assert "SECRET-DO-NOT-LEAK" not in out
    body = json.loads(out)
    assert body["ok"] is False
    assert body["error_kind"] == "stale_token"
