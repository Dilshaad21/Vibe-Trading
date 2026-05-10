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
        client_id: OAuth client id obtained at registration. INDMoney's
            token endpoint is a confidential client per RFC 6749 §2.3.1
            (``token_endpoint_auth_methods_supported``: ``client_secret_post``,
            ``client_secret_basic``) — refresh requests must include both
            ``client_id`` and ``client_secret`` or the endpoint rejects them.
        client_secret: OAuth client secret obtained at registration.
        backoff_seconds: Backoff between 5xx retries.
    """

    def __init__(
        self,
        *,
        url: str,
        token_cache: TokenCache,
        http: httpx.Client,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        backoff_seconds: float = 2.0,
    ) -> None:
        self.url = url
        self.tokens = token_cache
        self.http = http
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.backoff_seconds = backoff_seconds
        self._ids = itertools.count(1)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tools/call`` and return the unwrapped JSON result.

        Retries once on a service-error envelope (see
        ``_is_service_error_envelope``), matching the existing HTTP 5xx
        retry policy in ``_rpc``. INDMoney's ``/v1/holdings/`` backend
        has been observed to return a transient 513 wrapped as a 200 OK
        with this envelope; one retry after ``backoff_seconds`` clears
        it in practice.
        """
        params = {"name": name, "arguments": arguments}
        result = self._rpc("tools/call", params)
        if _is_service_error_envelope(result):
            time.sleep(self.backoff_seconds)
            result = self._rpc("tools/call", params)
            if _is_service_error_envelope(result):
                msg = result.get("message") or result.get("error")
                raise UpstreamError(f"INDMoney service error: {msg}")
        return result

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

        body = _parse_mcp_response_body(resp.text)
        if "error" in body:
            raise UpstreamError(f"INDMoney RPC error: {body['error']}")
        return _unwrap_tools_call_result(body.get("result", {}))

    def _post(self, payload: dict[str, Any], *, force_token: str | None = None) -> httpx.Response:
        if force_token:
            token = force_token
        else:
            cached = self.tokens.load()
            token = cached.access_token if cached else ""
        headers = {
            "content-type": "application/json",
            "accept": "application/json,text/event-stream",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.http.post(self.url, content=json.dumps(payload), headers=headers)

    def _refresh_http(self, refresh_token: str) -> dict[str, Any]:
        resp = self.http.post(
            self.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()


_SERVICE_ERROR_KEYS = frozenset({"error", "message", "service", "tool"})


def _is_service_error_envelope(payload: Any) -> bool:
    """Detect INDMoney's upstream service-error envelope.

    Some backend errors (notably ``513`` from ``/v1/holdings/``) come
    back as successful MCP responses *without* ``isError: true``:

        {"error":   "service_error",
         "message": "API returned 513: /v1/holdings/",
         "tool":    "networth_asset_holdings",
         "service": "ind-memory"}

    Without this check, ``_unwrap_tools_call_result`` returns the error
    dict as if it were a real payload, and downstream callers report
    "no holdings" instead of surfacing the upstream outage.
    """
    return isinstance(payload, dict) and _SERVICE_ERROR_KEYS.issubset(payload.keys())


def _parse_mcp_response_body(text: str) -> dict[str, Any]:
    """Parse an MCP HTTP response body, accepting either plain JSON or SSE.

    ``mcp.indmoney.com`` returns 200 responses as Server-Sent Events with a
    single ``event: message`` carrying one or more ``data:`` lines that
    concatenate into the JSON-RPC payload. We try plain JSON first (cheap)
    and fall back to extracting and joining the ``data:`` lines.
    """
    text = text.strip()
    if not text:
        raise UpstreamError("INDMoney returned an empty body")
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass  # try SSE path below
    data_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        raise UpstreamError(f"INDMoney response is neither JSON nor SSE: {text[:200]!r}")
    joined = "\n".join(data_lines)
    try:
        return json.loads(joined)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"INDMoney SSE data line is not JSON: {exc}") from exc


def _unwrap_tools_call_result(result: dict[str, Any]) -> dict[str, Any]:
    """Pull the JSON payload out of an MCP tools/call response.

    MCP tools/call returns ``{"content": [{"type": "json", "json": {...}}]}``
    or ``{"content": [{"type": "text", "text": "<JSON>"}]}``. When the
    upstream tool failed, the same envelope arrives with ``isError: true``
    and an error message in the text content — we raise ``UpstreamError``
    rather than handing the error string back as data.
    """
    content = result.get("content", [])
    if result.get("isError"):
        message = ""
        for item in content:
            if item.get("type") == "text" and "text" in item:
                message = item["text"]
                break
        raise UpstreamError(f"INDMoney tool error: {message or '<no message>'}")
    for item in content:
        if item.get("type") == "json" and "json" in item:
            return item["json"]
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except Exception:
                continue
    return result
