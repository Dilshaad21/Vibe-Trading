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


def _make_client(tmp_path: Path, handler) -> IndMoneyClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://mcp.indmoney.com")
    return IndMoneyClient(
        url="https://mcp.indmoney.com/mcp",
        token_cache=_seed_token(tmp_path),
        http=http,
        token_endpoint="https://mcp.indmoney.com/oauth/token",
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


def test_call_tool_401_then_refresh_then_retry(tmp_path: Path):
    state = {"calls": 0, "refresh_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            state["refresh_calls"] += 1
            return httpx.Response(200, json={"access_token": "acc_new", "refresh_token": "ref_new", "expires_in": 3600})
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": {"ok": True}}]},
        })

    client = _make_client(tmp_path, handler)
    result = client.call_tool("get_holdings", {})
    assert result == {"ok": True}
    assert state["refresh_calls"] == 1
    assert state["calls"] == 2


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
