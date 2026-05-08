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
    normalize_networth_holdings,
    normalize_networth_snapshot,
)
from src.integrations.indmoney.types import CashSnapshot
from src.tools.path_utils import _allowed_file_roots  # type: ignore[attr-defined]

DEFAULT_URL = os.getenv("INDMONEY_MCP_URL", "https://mcp.indmoney.com/mcp")
# RFC 8414 authorization-server metadata at
# https://mcp.indmoney.com/.well-known/oauth-authorization-server advertises
# token_endpoint = "https://mcp.indmoney.com/token". An earlier hardcoded
# default of "/oauth/token" was a v1 guess that returned 403 on every refresh.
DEFAULT_TOKEN_URL = os.getenv("INDMONEY_TOKEN_URL", "https://mcp.indmoney.com/token")
DEFAULT_HOLDINGS_TTL = int(os.getenv("INDMONEY_HOLDINGS_TTL_SECONDS", "900"))


def _configured_asset_types() -> list[str]:
    """Asset types to fetch on each holdings refresh.

    INDMoney's `networth_holdings` tool requires one call per asset_type, so
    the holdings tool loops over a configured set. Default covers the three
    asset types most users actually hold; override with a comma-separated
    INDMONEY_ASSET_TYPES env var (e.g. ``IND_STOCK,US_STOCK,MF,EPF,NPS``).

    Valid values per the live `asset_type` enum: IND_STOCK, MF, US_STOCK,
    BOND, EPF, NPS, SA, FD, CRYPTO, INSURANCE, VEHICLE, RE, RD, AIF, PMS,
    PPF.
    """
    raw = os.getenv("INDMONEY_ASSET_TYPES", "IND_STOCK,US_STOCK,MF")
    return [s.strip() for s in raw.split(",") if s.strip()]


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

        asset_types = _configured_asset_types()
        import httpx
        with httpx.Client(timeout=30.0) as http:
            client = IndMoneyClient(
                url=DEFAULT_URL, token_cache=tokens, http=http,
                token_endpoint=DEFAULT_TOKEN_URL,
                client_id=creds.client_id, client_secret=creds.client_secret,
            )
            try:
                with cache.lock(token.account_id):
                    snapshot_raw = client.call_tool("networth_snapshot", {})
                    holdings: list[dict[str, Any]] = []
                    for at in asset_types:
                        try:
                            payload = client.call_tool("networth_holdings",
                                                        {"asset_type": at})
                        except UpstreamError as exc:
                            # Skip individual asset types that error out (e.g.
                            # validation failures for unsupported types) but
                            # keep collecting the rest. Log to the audit trail.
                            append_audit(
                                cache.dir / "audit.log",
                                account=token.account_id,
                                action=f"fetch_holdings:{at}",
                                outcome="upstream_error",
                                detail=str(exc),
                            )
                            continue
                        for h in normalize_networth_holdings(at, payload):
                            holdings.append(h.to_dict())
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

        snapshot_norm = normalize_networth_snapshot(snapshot_raw)
        # CashSnapshot from this MCP is essentially empty: INDMoney does not
        # expose a free-cash field. The "Liquid" assetclass_l2 in the snapshot
        # is closest, but it includes FDs and savings, so we record it as
        # cash_inr for downstream visibility while keeping cash_usd at 0.
        liquid = next((a for a in snapshot_norm["assets"]
                       if a.get("assetclass_l2") == "Liquid"), {})
        cash = CashSnapshot(
            cash_usd=0.0,
            cash_inr=float(liquid.get("current_value", 0) or 0),
            pending_settlement_usd=0.0,
            asof="",
        )
        snapshot = {
            "asof": "",
            "account_id": token.account_id,
            "asset_types": asset_types,
            "totals": {
                "total_invested": snapshot_norm["total_invested"],
                "total_current_value": snapshot_norm["total_current_value"],
                "total_networth": snapshot_norm["total_networth"],
            },
            "investments_by_asset_type": snapshot_norm["investments"],
            "assets_by_class": snapshot_norm["assets"],
            "sector_breakdown": snapshot_norm["sector"],
            "holdings": holdings,
            "cash": cash.to_dict(),
        }
        snap_path = cache.put(token.account_id, "holdings", "current",
                              snapshot, ttl_seconds=DEFAULT_HOLDINGS_TTL)
        snapshot["snapshot_path"] = str(snap_path)
        cache.put(token.account_id, "holdings", "current",
                  snapshot, ttl_seconds=DEFAULT_HOLDINGS_TTL)
        append_audit(cache.dir / "audit.log",
                     account=token.account_id, action="fetch_holdings",
                     outcome="ok",
                     detail=f"{len(holdings)} positions across "
                            f"{len(asset_types)} asset types")
        return json.dumps({"ok": True, **snapshot, "from_cache": False})
