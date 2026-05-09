"""MacroSnapshotTool — exposes fetch_macro_snapshot() to the agent
registry (and via mcp_server.py, to MCP clients)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.integrations.macro.snapshot import fetch_macro_snapshot
from src.tools.path_utils import _allowed_file_roots  # type: ignore[attr-defined]

DEFAULT_TTL_SECONDS = int(os.getenv("MACRO_SNAPSHOT_TTL_SECONDS", "3600"))
_CACHE_SUBDIR = "macro"
_CACHE_FILENAME = "snapshot.json"


def _macro_cache_path() -> Path:
    """Return the cache file path. Lives under the first allowed file root
    so existing analytics tools can read it without sandbox tweaks.
    """
    root = _allowed_file_roots()[0]
    cache_dir = root / _CACHE_SUBDIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / _CACHE_FILENAME


def _read_cache() -> dict[str, Any] | None:
    path = _macro_cache_path()
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    expires_at = body.get("_expires_at", 0)
    if expires_at <= time.time():
        return None
    return body


def _write_cache(payload: dict[str, Any], *, ttl_seconds: int) -> Path:
    path = _macro_cache_path()
    payload = {**payload, "_expires_at": int(time.time()) + max(0, ttl_seconds)}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path


class MacroSnapshotTool(BaseTool):
    name = "macro_snapshot"
    description = (
        "Pull a current cross-asset macro snapshot — central-bank policy "
        "rates (Fed/ECB/BoE), US Treasury yields (2Y/10Y/30Y) + 2s10s spread, "
        "FX (USD/INR, DXY, EUR/USD, USD/JPY), and commodity benchmarks "
        "(Brent, WTI, gold). Sources: FRED public CSV + yfinance — no API "
        "keys required. Cache TTL 1 hour; pass force_refresh=true to skip. "
        "Partial-failure tolerant: a missing source surfaces in the _errors "
        "array; other fields stay populated."
    )
    is_readonly = True
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "force_refresh": {
                "type": "boolean",
                "description": "Skip the TTL cache and re-fetch from upstream sources.",
                "default": False,
            }
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        force_refresh = bool(kwargs.get("force_refresh", False))

        if not force_refresh:
            cached = _read_cache()
            if cached is not None:
                # Strip cache-internal field before returning.
                cached.pop("_expires_at", None)
                return json.dumps({"ok": True, **cached, "from_cache": True})

        payload = fetch_macro_snapshot()
        path = _write_cache(payload, ttl_seconds=DEFAULT_TTL_SECONDS)
        return json.dumps({
            "ok": True, **payload,
            "from_cache": False,
            "snapshot_path": str(path),
        })
