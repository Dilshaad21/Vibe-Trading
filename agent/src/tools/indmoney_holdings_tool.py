"""IndMoney holdings tool — read current positions + cash."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.integrations.indmoney import ErrorKind, build_error
from src.integrations.indmoney.audit import append_audit
from src.integrations.indmoney.auth import (
    ClientCredentials,
    ClientCredentialsMissingError,
    StaleTokenError,
    TokenCache,
)
from src.integrations.indmoney.cache import SnapshotCache
from src.integrations.indmoney.client import (
    IndMoneyClient,
    RateLimitedError,
    UpstreamError,
)
from src.integrations.indmoney.normalizer import (
    normalize_cash,
    normalize_holdings,
)
from src.tools.path_utils import _allowed_file_roots  # type: ignore[attr-defined]

DEFAULT_URL = os.getenv("INDMONEY_MCP_URL", "https://mcp.indmoney.com/mcp")
DEFAULT_TOKEN_URL = os.getenv("INDMONEY_TOKEN_URL", "https://mcp.indmoney.com/oauth/token")
DEFAULT_HOLDINGS_TTL = int(os.getenv("INDMONEY_HOLDINGS_TTL_SECONDS", "900"))


def is_remote_callsite() -> bool:
    return os.getenv("VIBE_TRADING_REMOTE_CALL", "0") == "1"


def gate_ok() -> bool:
    if not is_remote_callsite():
        return True
    return os.getenv("VIBE_TRADING_ENABLE_INDMONEY", "0") == "1"


def root_for_uploads() -> Path:
    """First allowed file root — matches existing tool conventions."""
    return _allowed_file_roots()[0]


class IndMoneyHoldingsTool(BaseTool):
    name = "indmoney_holdings"
    description = (
        "Read current INDMoney portfolio holdings and cash. "
        "Returns positions + cash + a snapshot file path. "
        "Cache-first (TTL 15 min); pass force_refresh=true to skip."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "force_refresh": {
                "type": "boolean",
                "description": "Skip the TTL cache and re-fetch from the MCP server.",
                "default": False,
            }
        },
        "required": [],
    }

    @classmethod
    def check_available(cls) -> bool:
        # Always available locally; gating happens at execute() time so we
        # can return a structured error instead of being silently dropped.
        return True

    def execute(self, **kwargs: Any) -> str:
        if not gate_ok():
            return json.dumps(build_error(
                ErrorKind.CONFIG_MISSING,
                "Set VIBE_TRADING_ENABLE_INDMONEY=1 to enable INDMoney from a remote caller.",
            ))

        force_refresh = bool(kwargs.get("force_refresh", False))

        cache = SnapshotCache(root=root_for_uploads())
        tokens = TokenCache()
        token = tokens.load()
        if token is None:
            return json.dumps(build_error(
                ErrorKind.NEEDS_AUTH,
                "Run: vibe-trading indmoney login",
                auth_url=None,
            ))

        cached = cache.get(token.account_id, "holdings", "current",
                           force_refresh=force_refresh)
        if cached is not None:
            return json.dumps({"ok": True, **cached, "from_cache": True})

        try:
            creds = ClientCredentials.load()
        except ClientCredentialsMissingError as exc:
            return json.dumps(build_error(ErrorKind.NEEDS_AUTH, str(exc)))

        import httpx
        with httpx.Client(timeout=30.0) as http:
            client = IndMoneyClient(
                url=DEFAULT_URL, token_cache=tokens, http=http,
                token_endpoint=DEFAULT_TOKEN_URL,
                client_id=creds.client_id, client_secret=creds.client_secret,
            )
            try:
                with cache.lock(token.account_id):
                    holdings_raw = client.call_tool("get_holdings", {})
                    cash_raw = client.call_tool("get_account", {})
            except StaleTokenError as exc:
                append_audit(cache.dir / "audit.log",
                             account=token.account_id, action="fetch_holdings",
                             outcome="stale_token", detail=str(exc))
                return json.dumps(build_error(ErrorKind.STALE_TOKEN,
                                              "Re-run: vibe-trading indmoney login"))
            except RateLimitedError as exc:
                append_audit(cache.dir / "audit.log",
                             account=token.account_id, action="fetch_holdings",
                             outcome="rate_limited", detail=str(exc))
                return json.dumps(build_error(ErrorKind.RATE_LIMITED, str(exc),
                                              retry_after_seconds=exc.retry_after_seconds))
            except UpstreamError as exc:
                append_audit(cache.dir / "audit.log",
                             account=token.account_id, action="fetch_holdings",
                             outcome="upstream_error", detail=str(exc))
                return json.dumps(build_error(ErrorKind.UPSTREAM_ERROR, str(exc)))
            except TimeoutError as exc:
                return json.dumps(build_error(ErrorKind.UPSTREAM_ERROR,
                                              f"Lock contention: {exc}"))

        holdings = [h.to_dict() for h in normalize_holdings(holdings_raw)]
        cash = normalize_cash(cash_raw).to_dict()
        snapshot = {
            "asof": holdings_raw.get("asof") or cash_raw.get("asof") or "",
            "account_id": token.account_id,
            "holdings": holdings,
            "cash": cash,
        }
        snap_path = cache.put(token.account_id, "holdings", "current",
                              snapshot, ttl_seconds=DEFAULT_HOLDINGS_TTL)
        # Persist the snapshot path inside the cached value so subsequent
        # cache hits return the same envelope shape as a fresh fetch.
        snapshot["snapshot_path"] = str(snap_path)
        cache.put(token.account_id, "holdings", "current",
                  snapshot, ttl_seconds=DEFAULT_HOLDINGS_TTL)
        append_audit(cache.dir / "audit.log",
                     account=token.account_id, action="fetch_holdings",
                     outcome="ok",
                     detail=f"{len(holdings)} positions")
        return json.dumps({"ok": True, **snapshot, "from_cache": False})
