"""Tests for IndMoneyClient (MCP wrapper) using a stub transport."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache
from src.integrations.indmoney.client import IndMoneyClient


def _seed_token(tmp_path: Path) -> TokenCache:
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(Token(
        access_token="acc_ok", refresh_token="ref_ok",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))
    return cache


def _make_client(tmp_path: Path, handler, *,
                 client_id: str = "cid_test",
                 client_secret: str = "csec_test") -> IndMoneyClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://mcp.indmoney.com")
    return IndMoneyClient(
        url="https://mcp.indmoney.com/mcp",
        token_cache=_seed_token(tmp_path),
        http=http,
        token_endpoint="https://mcp.indmoney.com/oauth/token",
        client_id=client_id,
        client_secret=client_secret,
    )


def test_call_tool_happy_path(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "get_holdings"
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": {"positions": []}}]},
        })

    client = _make_client(tmp_path, handler)
    result = client.call_tool("get_holdings", {})
    assert result == {"positions": []}


def test_call_tool_handles_sse_framed_response(tmp_path: Path):
    """mcp.indmoney.com returns 200s as Server-Sent Events:
    `event: message\\ndata: {jsonrpc...}\\n\\n`. The client must
    parse the data: line, not call resp.json() on the SSE body."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sse = (
            "event: message\n"
            "data: " + json.dumps({
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"content": [{"type": "text",
                                          "text": '{"positions": [{"investment_code": "112192"}]}'}]},
            }) + "\n\n"
        )
        return httpx.Response(
            200,
            content=sse.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    client = _make_client(tmp_path, handler)
    result = client.call_tool("networth_holdings", {"asset_type": "US_STOCK"})
    assert result == {"positions": [{"investment_code": "112192"}]}


def test_call_tool_raises_on_mcp_iserror_envelope(tmp_path: Path):
    """When MCP returns {"content": [...], "isError": true}, the client
    must raise UpstreamError instead of handing the error string back as
    if it were data."""
    from src.integrations.indmoney.client import UpstreamError

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {
                "content": [{"type": "text",
                             "text": "Error executing tool networth_holdings: 1 validation error"}],
                "isError": True,
            },
        })

    client = _make_client(tmp_path, handler)
    with pytest.raises(UpstreamError) as exc_info:
        client.call_tool("networth_holdings", {"asset_type": "STOCK"})
    assert "validation error" in str(exc_info.value)


def test_call_tool_falls_back_to_plain_json_when_no_sse_framing(tmp_path: Path):
    """If the upstream returns plain JSON (no event:/data: framing), the
    client must still parse it — the parser is tolerant either way."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"],
                   "result": {"content": [{"type": "json", "json": {"ok": True}}]}},
        )

    client = _make_client(tmp_path, handler)
    result = client.call_tool("networth_snapshot", {})
    assert result == {"ok": True}


def test_call_tool_401_then_refresh_then_retry(tmp_path: Path):
    state = {"calls": 0, "refresh_calls": 0, "refresh_body": b""}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            state["refresh_calls"] += 1
            state["refresh_body"] = bytes(request.content)
            return httpx.Response(200, json={"access_token": "acc_new", "refresh_token": "ref_new", "expires_in": 3600})
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": {"ok": True}}]},
        })

    client = _make_client(tmp_path, handler,
                          client_id="cid_xyz", client_secret="csec_xyz")
    result = client.call_tool("get_holdings", {})
    assert result == {"ok": True}
    assert state["refresh_calls"] == 1
    assert state["calls"] == 2
    # INDMoney is a confidential client (token_endpoint_auth_methods_supported
    # = client_secret_post / _basic). The refresh POST must include the
    # client_id and client_secret or the token endpoint rejects it.
    body = state["refresh_body"].decode("utf-8")
    assert "client_id=cid_xyz" in body
    assert "client_secret=csec_xyz" in body
    assert "grant_type=refresh_token" in body
    assert "refresh_token=ref_ok" in body


def test_call_tool_401_then_refresh_fails_raises(tmp_path: Path):
    from src.integrations.indmoney.auth import StaleTokenError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(401)

    client = _make_client(tmp_path, handler)
    with pytest.raises(StaleTokenError):
        client.call_tool("get_holdings", {})


def test_call_tool_429_honours_retry_after(tmp_path: Path):
    from src.integrations.indmoney.client import RateLimitedError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "13"}, json={"error": "throttled"})

    client = _make_client(tmp_path, handler)
    with pytest.raises(RateLimitedError) as exc_info:
        client.call_tool("get_holdings", {})
    assert exc_info.value.retry_after_seconds == 13


def test_call_tool_5xx_retries_once_then_upstream_error(tmp_path: Path):
    from src.integrations.indmoney.client import UpstreamError

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(503, json={"error": "down"})

    client = _make_client(tmp_path, handler)
    with pytest.raises(UpstreamError):
        client.call_tool("get_holdings", {})
    assert state["calls"] == 2


def test_call_tool_retries_on_service_error_envelope(tmp_path: Path):
    """INDMoney sometimes wraps backend errors (513 from /v1/holdings/) as
    a 200 OK MCP response with no isError flag. The client must detect the
    envelope and retry once before treating it as data."""
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["calls"] += 1
        if state["calls"] == 1:
            payload = {
                "error": "service_error",
                "message": "API returned 513: /v1/holdings/",
                "tool": "networth_asset_holdings",
                "service": "ind-memory",
            }
        else:
            payload = {"holdings": [{"investment_code": "117123",
                                       "investment": "CloudFlare Inc."}]}
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": payload}]},
        })

    client = _make_client(tmp_path, handler)
    client.backoff_seconds = 0  # don't sleep in the test
    result = client.call_tool("networth_holdings", {"asset_type": "US_STOCK"})
    assert state["calls"] == 2
    assert result == {"holdings": [{"investment_code": "117123",
                                      "investment": "CloudFlare Inc."}]}


def test_call_tool_raises_upstream_error_on_persistent_service_error(tmp_path: Path):
    from src.integrations.indmoney.client import UpstreamError

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["calls"] += 1
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": {
                "error": "service_error",
                "message": "API returned 513: /v1/holdings/",
                "tool": "networth_asset_holdings",
                "service": "ind-memory",
            }}]},
        })

    client = _make_client(tmp_path, handler)
    client.backoff_seconds = 0
    with pytest.raises(UpstreamError) as exc_info:
        client.call_tool("networth_holdings", {"asset_type": "US_STOCK"})
    assert "513" in str(exc_info.value)
    assert state["calls"] == 2
