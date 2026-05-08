"""IndMoney transactions tool — date-range history → TradeRecord CSV + events CSV."""

from __future__ import annotations

import json
import os
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
    normalize_transactions,
    write_events_csv,
    write_trades_csv,
)
from src.tools.indmoney_holdings_tool import (
    DEFAULT_URL,
    DEFAULT_TOKEN_URL,
    gate_ok,
    root_for_uploads,
)

DEFAULT_TXNS_TTL = int(os.getenv("INDMONEY_TXNS_TTL_SECONDS", "86400"))


class IndMoneyTransactionsTool(BaseTool):
    name = "indmoney_transactions"
    description = (
        "Read INDMoney transaction history for a date range. "
        "Writes a TradeRecord-compatible CSV (consumable by trade_journal_tool) "
        "and a sibling events CSV for dividends / splits / corporate actions. "
        "Cache-first (TTL 24h); pass force_refresh=true to skip."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            "end_date":   {"type": "string", "description": "ISO date YYYY-MM-DD"},
            "force_refresh": {"type": "boolean", "default": False},
        },
        "required": ["start_date", "end_date"],
    }

    def execute(self, **kwargs: Any) -> str:
        if not gate_ok():
            return json.dumps(build_error(
                ErrorKind.CONFIG_MISSING,
                "Set VIBE_TRADING_ENABLE_INDMONEY=1 to enable INDMoney from a remote caller.",
            ))

        start = str(kwargs["start_date"])
        end = str(kwargs["end_date"])
        force_refresh = bool(kwargs.get("force_refresh", False))

        cache = SnapshotCache(root=root_for_uploads())
        tokens = TokenCache()
        token = tokens.load()
        if token is None:
            return json.dumps(build_error(
                ErrorKind.NEEDS_AUTH,
                "Run: vibe-trading indmoney login",
            ))

        key = f"{start}_{end}"
        cached = cache.get(token.account_id, "transactions", key,
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
                    raw = client.call_tool("get_transactions",
                                           {"start_date": start, "end_date": end})
            except StaleTokenError as exc:
                append_audit(cache.dir / "audit.log",
                             account=token.account_id, action="fetch_transactions",
                             outcome="stale_token", detail=str(exc))
                return json.dumps(build_error(ErrorKind.STALE_TOKEN,
                                              "Re-run: vibe-trading indmoney login"))
            except RateLimitedError as exc:
                return json.dumps(build_error(ErrorKind.RATE_LIMITED, str(exc),
                                              retry_after_seconds=exc.retry_after_seconds))
            except UpstreamError as exc:
                return json.dumps(build_error(ErrorKind.UPSTREAM_ERROR, str(exc)))
            except TimeoutError as exc:
                return json.dumps(build_error(ErrorKind.UPSTREAM_ERROR,
                                              f"Lock contention: {exc}"))

        trades, events = normalize_transactions(raw)
        cache.dir.mkdir(parents=True, exist_ok=True)
        trades_csv = cache.dir / f"{token.account_id}_{start}_{end}_txns.csv"
        events_csv = cache.dir / f"{token.account_id}_{start}_{end}_events.csv"
        write_trades_csv(trades, trades_csv)
        write_events_csv(events, events_csv)

        snapshot = {
            "account_id": token.account_id,
            "date_range": [start, end],
            "count": len(trades),
            "events_count": len(events),
            "csv_path": str(trades_csv),
            "events_csv_path": str(events_csv),
        }
        snap_path = cache.put(token.account_id, "transactions", key,
                              snapshot, ttl_seconds=DEFAULT_TXNS_TTL)
        append_audit(cache.dir / "audit.log",
                     account=token.account_id, action="fetch_transactions",
                     outcome="ok",
                     detail=f"{len(trades)} trades + {len(events)} events")
        return json.dumps({"ok": True, **snapshot,
                           "snapshot_path": str(snap_path),
                           "from_cache": False})
