"""IndMoney sync tool — force-refresh the holdings cache.

In v2 this collapses to "refresh the holdings snapshot". Earlier
revisions also pulled transaction history, but INDMoney's MCP does not
expose any transaction stream (no `get_transactions` tool, no analog),
so the transactions branch was dropped. The tool name is kept for
registry-stability reasons — anything that wired up `indmoney_sync`
keeps working with the new behavior.
"""

from __future__ import annotations

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


class IndMoneySyncTool(BaseTool):
    name = "indmoney_sync"
    description = (
        "Force-refresh the INDMoney holdings cache. Calls "
        "networth_snapshot + networth_holdings per configured asset type, "
        "writes a fresh snapshot, and prunes snapshots older than 30 days."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {},
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
                "Run: python scripts/indmoney_oauth.py",
                auth_url=None,
            ))

        holdings_out = json.loads(
            IndMoneyHoldingsTool().execute(force_refresh=True)
        )
        if not holdings_out.get("ok"):
            return json.dumps({**holdings_out,
                                "status": holdings_out.get("error_kind", "error")})

        cache = SnapshotCache(root=root_for_uploads())
        pruned = cache.prune(max_age_days=30)
        append_audit(cache.dir / "audit.log",
                     account=token.account_id, action="sync",
                     outcome="ok",
                     detail=f"holdings={len(holdings_out['holdings'])} "
                            f"pruned={pruned}")

        return json.dumps({
            "ok": True,
            "status": "ok",
            "asof": holdings_out.get("asof", ""),
            "holdings_count": len(holdings_out["holdings"]),
            "snapshot_path": holdings_out["snapshot_path"],
            "totals": holdings_out.get("totals", {}),
            "pruned_files": pruned,
        })
