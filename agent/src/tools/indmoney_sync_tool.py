"""IndMoney sync tool — refresh holdings + cash + recent transactions in one call."""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from src.agent.tools import BaseTool
from src.integrations.indmoney import ErrorKind, build_error
from src.integrations.indmoney.audit import append_audit
from src.integrations.indmoney.auth import TokenCache
from src.integrations.indmoney.cache import SnapshotCache
from src.tools.indmoney_holdings_tool import (
    IndMoneyHoldingsTool,
    gate_ok,
    root_for_uploads,
)
from src.tools.indmoney_transactions_tool import IndMoneyTransactionsTool


def _default_since() -> str:
    return (_dt.date.today() - _dt.timedelta(days=30)).isoformat()


class IndMoneySyncTool(BaseTool):
    name = "indmoney_sync"
    description = (
        "Force-refresh INDMoney holdings + cash + recent transactions in one call. "
        "Use after broker activity to bring caches up to date."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "include_transactions_since": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD; default: 30 days ago.",
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        if not gate_ok():
            return json.dumps(build_error(
                ErrorKind.CONFIG_MISSING,
                "Set VIBE_TRADING_ENABLE_INDMONEY=1 to enable INDMoney from a remote caller.",
            ))

        token = TokenCache().load()
        if token is None:
            return json.dumps(build_error(
                ErrorKind.NEEDS_AUTH,
                "Run: vibe-trading indmoney login",
                auth_url=None,
            ))

        since = str(kwargs.get("include_transactions_since") or _default_since())
        today = _dt.date.today().isoformat()

        holdings_out = json.loads(
            IndMoneyHoldingsTool().execute(force_refresh=True)
        )
        if not holdings_out.get("ok"):
            return json.dumps({**holdings_out, "status": holdings_out.get("error_kind", "error")})

        txns_out = json.loads(
            IndMoneyTransactionsTool().execute(
                start_date=since, end_date=today, force_refresh=True,
            )
        )
        if not txns_out.get("ok"):
            return json.dumps({**txns_out, "status": txns_out.get("error_kind", "error")})

        cache = SnapshotCache(root=root_for_uploads())
        pruned = cache.prune(max_age_days=30)
        append_audit(cache.dir / "audit.log",
                     account=token.account_id, action="sync",
                     outcome="ok",
                     detail=f"holdings={len(holdings_out['holdings'])} "
                            f"txns={txns_out['count']} pruned={pruned}")

        return json.dumps({
            "ok": True,
            "status": "ok",
            "asof": holdings_out.get("asof", ""),
            "holdings_count": len(holdings_out["holdings"]),
            "transactions_count": txns_out["count"],
            "snapshot_path": holdings_out["snapshot_path"],
            "transactions_csv": txns_out["csv_path"],
            "events_csv": txns_out["events_csv_path"],
            "pruned_files": pruned,
        })
