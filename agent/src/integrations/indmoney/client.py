"""INDMoney MCP HTTP client.

Speaks JSON-RPC 2.0 over HTTPS to ``mcp.indmoney.com/mcp``. Handles:
  - Authorization: Bearer <access_token>
  - 401 -> refresh token -> retry once
  - 429 -> raise RateLimitedError with Retry-After
  - 5xx -> one retry with 2s backoff, then UpstreamError

The caller passes in an ``httpx.Client`` and reuses it for the lifetime of a
tool invocation. This keeps Cloudflare's ``__cf_bm`` cookie and TLS session
sticky across call_tool / refresh / retry, which the upstream Cloudflare
edge expects (per Task 0 discovery: mcp.indmoney.com sits behind cf-ray).
"""

from __future__ import annotations

import itertools
import json
import logging
import time
from typing import Any

import httpx

from src.integrations.indmoney.auth import StaleTokenError, TokenCache

logger = logging.getLogger(__name__)


class RateLimitedError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"INDMoney rate-limited (retry_after={retry_after_seconds}s)")
        self.retry_after_seconds = retry_after_seconds


class UpstreamError(RuntimeError):
    pass


class IndMoneyClient:
    """Thin MCP-over-HTTP client.

    Args:
        url: MCP endpoint, e.g. ``https://mcp.indmoney.com/mcp``.
        token_cache: TokenCache instance (used for current token + refresh).
        http: ``httpx.Client`` (injectable for tests). Reuse one client per
            tool invocation so Cloudflare cookies and TLS state stay sticky.
        token_endpoint: OAuth token URL for refresh.
        backoff_seconds: Backoff between 5xx retries.
    """

    def __init__(
        self,
        *,
        url: str,
        token_cache: TokenCache,
        http: httpx.Client,
        token_endpoint: str,
        backoff_seconds: float = 2.0,
    ) -> None:
        self.url = url
        self.tokens = token_cache
        self.http = http
        self.token_endpoint = token_endpoint
        self.backoff_seconds = backoff_seconds
        self._ids = itertools.count(1)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tools/call`` and return the unwrapped JSON result."""
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(self._ids),
                   "method": method, "params": params}
        resp = self._post(payload)

        if resp.status_code == 401:
            new = self.tokens.refresh(
                token_endpoint=self.token_endpoint,
                http_post=self._refresh_http,
            )
            resp = self._post(payload, force_token=new.access_token)

        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", "1") or "1")
            raise RateLimitedError(retry)

        if 500 <= resp.status_code < 600:
            time.sleep(self.backoff_seconds)
            resp = self._post(payload)
            if 500 <= resp.status_code < 600:
                raise UpstreamError(f"INDMoney {resp.status_code}: {resp.text[:200]}")

        if resp.status_code != 200:
            raise UpstreamError(f"INDMoney {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        if "error" in body:
            raise UpstreamError(f"INDMoney RPC error: {body['error']}")
        return _unwrap_tools_call_result(body.get("result", {}))

    def _post(self, payload: dict[str, Any], *, force_token: str | None = None) -> httpx.Response:
        token = force_token or (self.tokens.load().access_token if self.tokens.load() else "")
        headers = {
            "Authorization": f"Bearer {token}" if token else "",
            "content-type": "application/json",
            "accept": "application/json,text/event-stream",
        }
        return self.http.post(self.url, content=json.dumps(payload), headers=headers)

    def _refresh_http(self, refresh_token: str) -> dict[str, Any]:
        resp = self.http.post(
            self.token_endpoint,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()


def _unwrap_tools_call_result(result: dict[str, Any]) -> dict[str, Any]:
    """Pull the JSON payload out of an MCP tools/call response.

    MCP tools/call returns ``{"content": [{"type": "json", "json": {...}}]}``
    (or "text" content). We unwrap to the bare dict for callers.
    """
    content = result.get("content", [])
    for item in content:
        if item.get("type") == "json" and "json" in item:
            return item["json"]
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except Exception:
                continue
    return result
