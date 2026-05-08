"""One-shot discovery of mcp.indmoney.com/mcp.

Run interactively to confirm:
  - Auth shape (OAuth metadata vs static key)
  - Tool list, input/output schemas
  - Sample payload shapes for holdings / transactions / cash
  - Rate-limit headers (X-RateLimit-Limit, Retry-After)

NOT used in production. Discovery output is committed to:
  docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md
  agent/tests/fixtures/indmoney/discovery.json

Sanitize before commit: redact account numbers, tokens, real symbols.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

DEFAULT_URL = "https://mcp.indmoney.com/mcp"
FIXTURE_PATH = Path(__file__).resolve().parent.parent / "agent/tests/fixtures/indmoney/discovery.json"


async def discover(url: str) -> dict:
    """Probe the MCP server for auth metadata and tool list."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        oauth_meta = None
        try:
            r = await http.get(url.replace("/mcp", "/.well-known/oauth-authorization-server"))
            if r.status_code == 200:
                oauth_meta = r.json()
        except Exception as exc:
            print(f"[oauth-discovery] {exc}", file=sys.stderr)

        # RFC 9728: protected-resource metadata. Some servers (incl. INDMoney) advertise
        # this via the WWW-Authenticate `resource_metadata=` parameter on a 401.
        protected_resource_meta = None
        try:
            r = await http.get(url.replace("/mcp", "/.well-known/oauth-protected-resource"))
            if r.status_code == 200:
                protected_resource_meta = r.json()
        except Exception as exc:
            print(f"[protected-resource-discovery] {exc}", file=sys.stderr)

        access_token = os.getenv("INDMONEY_ACCESS_TOKEN", "").strip()
        headers = {"accept": "application/json,text/event-stream"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        init_payload = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "vibe-trading-discover", "version": "0.0.1"}},
        }
        try:
            init_resp = await http.post(url, json=init_payload, headers=headers)
            init_status = init_resp.status_code
            init_headers = dict(init_resp.headers)
            init_body = _safe_body(init_resp)
        except Exception as exc:
            init_status = -1
            init_headers = {"_error": str(exc)}
            init_body = None

        tools_list = None
        if access_token and init_status == 200:
            try:
                resp = await http.post(url, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
                }, headers=headers)
                tools_list = _safe_body(resp)
            except Exception as exc:
                tools_list = {"_error": str(exc)}

        return {
            "oauth_metadata": oauth_meta,
            "protected_resource_metadata": protected_resource_meta,
            "initialize_status": init_status,
            "initialize_headers": init_headers,
            "initialize_body": init_body,
            "tools_list": tools_list,
        }


def _safe_body(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text[:2000]


def main() -> int:
    url = os.getenv("INDMONEY_MCP_URL", DEFAULT_URL)
    print(f"[discover] {url}")
    result = asyncio.run(discover(url))

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"[discover] wrote {FIXTURE_PATH}")
    print(json.dumps(result, indent=2, default=str)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
