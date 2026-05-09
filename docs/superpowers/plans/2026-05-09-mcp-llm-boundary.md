# MCP / LLM boundary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the most-used data-heavy swarm presets with deterministic MCP tools + recipe skills so a Claude-Code-via-`vibe-trading-mcp` session can run macro / portfolio / fundamental analyses without configuring a second LLM.

**Architecture:** One new MCP tool (`macro_snapshot`) pulls central-bank rates, yields, FX, commodities from public sources (FRED CSV + yfinance, no API keys). Three new recipe SKILL.md files (siblings of the existing 74 skills, tagged `category: recipe`) document step-by-step orchestration that Claude Code follows with one LLM voice. CLAUDE.md gains a boundary section + a feature-matrix companion doc.

**Tech Stack:** Python 3.11+, `httpx` (already a dep — used here for FRED CSV fetch), `yfinance` (already a dep — used by `agent/backtest/loaders/yfinance_loader.py`), `pandas` (already a dep), `fastmcp` (already a dep). Tests use `pytest`.

**Spec:** [`docs/superpowers/specs/2026-05-09-mcp-llm-boundary-design.md`](../specs/2026-05-09-mcp-llm-boundary-design.md).

**Test command:**
```bash
/tmp/venv/bin/pytest --ignore=agent/tests/e2e_backtest --tb=short -q
```

**Commit style:** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`). Hooks not skipped.

---

## File map

Created (new):
- `agent/src/integrations/__init__.py` — already exists
- `agent/src/integrations/macro/__init__.py` — package marker + public exports
- `agent/src/integrations/macro/snapshot.py` — `fetch_macro_snapshot()` orchestrator
- `agent/src/integrations/macro/sources.py` — pure `_fred_csv_latest()` + `_yfinance_latest()` helpers
- `agent/src/integrations/macro/README.md` — usage notes
- `agent/src/tools/macro_snapshot_tool.py` — `MacroSnapshotTool(BaseTool)`
- `agent/src/skills/macro-rates-fx-analysis/SKILL.md`
- `agent/src/skills/portfolio-rebalance/SKILL.md`
- `agent/src/skills/equity-fundamental-deep-dive/SKILL.md`
- `agent/tests/test_macro_snapshot.py` — unit tests on normalizer + partial-failure
- `agent/tests/test_macro_snapshot_tool_contract.py` — tool execute() end-to-end
- `agent/tests/test_recipe_skills_loadable.py` — list_skills() + frontmatter checks
- `docs/mcp-feature-matrix.md` — preset → recipe / swarm / pending matrix

Modified:
- `agent/mcp_server.py` — add `@mcp.tool` wrapper for `macro_snapshot` (count goes 24 → 25)
- `agent/src/agent/skills.py` — append `"recipe"` to `_CATEGORY_ORDER`
- `agent/tests/test_indmoney_registry.py` — extend or duplicate the FastMCP-surface assertion to also check `macro_snapshot` is exposed (single-line assertion add)
- `CLAUDE.md` — add "MCP / LLM boundary" section after "Skill namespaces"

---

## Task 1: macro snapshot data fetcher (pure, no MCP wiring yet)

**Files:**
- Create: `agent/src/integrations/macro/__init__.py`
- Create: `agent/src/integrations/macro/sources.py`
- Create: `agent/src/integrations/macro/snapshot.py`
- Test: `agent/tests/test_macro_snapshot.py`

> **Why pure first:** `snapshot.py` accepts injected getters so tests can stub network without `httpx.MockTransport` ceremony. The MCP wrapper in Task 2 wires up the real getters.

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_macro_snapshot.py`:

```python
"""Tests for the macro snapshot fetcher (pure, no network)."""

from __future__ import annotations


def test_fetch_macro_snapshot_happy_path():
    """All sources return; output has every expected field populated and no errors."""
    from src.integrations.macro.snapshot import fetch_macro_snapshot

    fred_calls: list[str] = []
    yf_calls: list[str] = []

    def fake_fred(series_id: str) -> float:
        fred_calls.append(series_id)
        return {
            "DFEDTARU": 5.50, "DFEDTARL": 5.25, "ECBDFR": 4.00,
            "IUDSOIA": 5.20, "DGS2": 4.81, "DGS10": 4.34, "DGS30": 4.52,
        }[series_id]

    def fake_yf(ticker: str) -> float:
        yf_calls.append(ticker)
        return {
            "INR=X": 83.45, "DX-Y.NYB": 104.21,
            "EURUSD=X": 1.08, "JPY=X": 152.30,
            "BZ=F": 84.20, "CL=F": 80.05, "GC=F": 2310.50,
            "^TNX": 4.34,
        }[ticker]

    snap = fetch_macro_snapshot(fred_getter=fake_fred, yf_getter=fake_yf)

    # Top-level structure
    assert "asof" in snap
    assert "central_bank_rates" in snap
    assert "yields" in snap
    assert "fx" in snap
    assert "commodities" in snap
    assert snap["_errors"] == []

    # Spot-check a few fields
    assert snap["central_bank_rates"]["fed_funds_target_upper"] == 5.50
    assert snap["central_bank_rates"]["fed_funds_target_lower"] == 5.25
    assert snap["central_bank_rates"]["ecb_deposit"] == 4.00
    assert snap["yields"]["ust_2y"] == 4.81
    assert snap["yields"]["ust_10y"] == 4.34
    assert snap["yields"]["us_2s10s_bp"] == round((4.34 - 4.81) * 100)
    assert snap["fx"]["usd_inr"] == 83.45
    assert snap["commodities"]["gold_usd_oz"] == 2310.50

    # Provenance recorded
    assert "fed_funds_target_upper" in snap["_sources"]
    assert snap["_sources"]["ust_10y"].startswith("FRED:")


def test_fetch_macro_snapshot_partial_failure_records_errors():
    """If FRED 503s for one series and yfinance returns NaN for another,
    the snapshot still returns; failed fields are null and _errors lists them."""
    from src.integrations.macro.snapshot import fetch_macro_snapshot

    def flaky_fred(series_id: str) -> float:
        if series_id == "ECBDFR":
            raise RuntimeError("FRED 503")
        return 5.50

    def flaky_yf(ticker: str) -> float:
        if ticker == "INR=X":
            return float("nan")  # yfinance returns NaN on missing
        return 100.0

    snap = fetch_macro_snapshot(fred_getter=flaky_fred, yf_getter=flaky_yf)

    # Failed fields are null, not omitted
    assert snap["central_bank_rates"]["ecb_deposit"] is None
    assert snap["fx"]["usd_inr"] is None

    # Successful fields still populated
    assert snap["central_bank_rates"]["fed_funds_target_upper"] == 5.50
    assert snap["fx"]["dxy"] == 100.0

    # Errors are surfaced
    err_fields = {e["field"] for e in snap["_errors"]}
    assert "ecb_deposit" in err_fields
    assert "usd_inr" in err_fields
    assert "FRED 503" in next(e for e in snap["_errors"] if e["field"] == "ecb_deposit")["reason"]


def test_fetch_macro_snapshot_2s10s_handles_null():
    """If either UST 2Y or 10Y is null, us_2s10s_bp must be null too."""
    from src.integrations.macro.snapshot import fetch_macro_snapshot

    def fred_missing_2y(series_id: str) -> float:
        if series_id == "DGS2":
            raise RuntimeError("not available")
        return 4.34  # everything else

    snap = fetch_macro_snapshot(
        fred_getter=fred_missing_2y, yf_getter=lambda t: 100.0,
    )

    assert snap["yields"]["ust_2y"] is None
    assert snap["yields"]["ust_10y"] == 4.34
    assert snap["yields"]["us_2s10s_bp"] is None
```

- [ ] **Step 2: Run — verify failure**

```bash
cd /Users/dmuthalif/Desktop/vibe-project/Vibe-Trading
/tmp/venv/bin/pytest agent/tests/test_macro_snapshot.py -v
```

Expected: ImportError (the module doesn't exist yet).

- [ ] **Step 3: Implement sources.py**

Create `agent/src/integrations/macro/sources.py`:

```python
"""Network-touching getters for macro_snapshot.

Each getter is a thin function that takes a single string identifier
(FRED series id / yfinance ticker) and returns a float, or raises
RuntimeError. The orchestrator in snapshot.py injects them so unit tests
can stub the network entirely.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
import pandas as pd

_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def fred_csv_latest(series_id: str, *, timeout: float = 15.0) -> float:
    """Fetch the most recent observation of a FRED series via the public
    CSV endpoint. No API key required.

    The CSV format is two columns: ``observation_date,<SERIES_ID>``. We
    pull the last row that has a numeric value (FRED uses ``.`` for missing).

    Raises:
        RuntimeError: HTTP failure, no numeric rows, or parse error.
    """
    url = _FRED_CSV_URL.format(series=series_id)
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    except Exception as exc:
        raise RuntimeError(f"FRED HTTP error for {series_id}: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"FRED HTTP {resp.status_code} for {series_id}")
    try:
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception as exc:
        raise RuntimeError(f"FRED CSV parse failed for {series_id}: {exc}") from exc
    if df.empty or series_id not in df.columns:
        raise RuntimeError(f"FRED CSV missing series column for {series_id}")
    series = pd.to_numeric(df[series_id], errors="coerce").dropna()
    if series.empty:
        raise RuntimeError(f"FRED series {series_id} has no numeric observations")
    return float(series.iloc[-1])


def yfinance_latest(ticker: str) -> float:
    """Fetch the most recent close for a yfinance ticker.

    Wraps ``yfinance.Ticker(...).history(period='5d')`` (5d gives buffer
    against weekend/holiday gaps). Returns the last non-NaN close.

    Raises:
        RuntimeError: yfinance error or no usable rows.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(f"yfinance not installed: {exc}") from exc
    try:
        hist = yf.Ticker(ticker).history(period="5d")
    except Exception as exc:
        raise RuntimeError(f"yfinance error for {ticker}: {exc}") from exc
    if hist.empty or "Close" not in hist.columns:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    closes = hist["Close"].dropna()
    if closes.empty:
        raise RuntimeError(f"yfinance returned only NaN closes for {ticker}")
    return float(closes.iloc[-1])
```

- [ ] **Step 4: Implement snapshot.py**

Create `agent/src/integrations/macro/snapshot.py`:

```python
"""Pull a current macro snapshot — central-bank rates, yields, FX,
commodities — from public sources. No API keys required.

The fetcher is partial-failure-tolerant: if one source fails, the
corresponding field becomes ``None`` and an entry lands in the
top-level ``_errors`` list. The tool layer surfaces ``_errors`` to
the caller so the agent can decide whether to proceed.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Mapping: snapshot field name → (group, source_kind, source_id)
# Order matters only for deterministic _sources output.
_FIELDS: list[tuple[str, str, str, str]] = [
    # group, field, kind, id
    ("central_bank_rates", "fed_funds_target_upper", "FRED", "DFEDTARU"),
    ("central_bank_rates", "fed_funds_target_lower", "FRED", "DFEDTARL"),
    ("central_bank_rates", "ecb_deposit",            "FRED", "ECBDFR"),
    ("central_bank_rates", "boe_bank_rate",          "FRED", "IUDSOIA"),
    # NB: RBI repo and BoJ policy rates are not consistently available on
    # FRED. They are intentionally omitted from v1 — Claude Code can fall
    # back to web_search() in the recipe step.
    ("yields", "ust_2y",  "FRED", "DGS2"),
    ("yields", "ust_10y", "FRED", "DGS10"),
    ("yields", "ust_30y", "FRED", "DGS30"),
    ("fx", "usd_inr",  "yfinance", "INR=X"),
    ("fx", "dxy",      "yfinance", "DX-Y.NYB"),
    ("fx", "eur_usd",  "yfinance", "EURUSD=X"),
    ("fx", "usd_jpy",  "yfinance", "JPY=X"),
    ("commodities", "brent_usd",  "yfinance", "BZ=F"),
    ("commodities", "wti_usd",    "yfinance", "CL=F"),
    ("commodities", "gold_usd_oz", "yfinance", "GC=F"),
]


def _safe_float(value: Any) -> float | None:
    """Convert to float and reject NaN. Used to guard yfinance NaN responses."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def fetch_macro_snapshot(
    *,
    fred_getter: Callable[[str], float] | None = None,
    yf_getter: Callable[[str], float] | None = None,
) -> dict[str, Any]:
    """Build the full macro snapshot.

    Args:
        fred_getter: Callable taking a FRED series id and returning the
            latest float observation. Defaults to the live HTTP getter.
        yf_getter: Callable taking a yfinance ticker and returning the
            latest float close. Defaults to the live yfinance getter.

    Returns:
        A dict with the shape documented in the spec
        (docs/superpowers/specs/2026-05-09-mcp-llm-boundary-design.md §4).
    """
    if fred_getter is None:
        from src.integrations.macro.sources import fred_csv_latest
        fred_getter = fred_csv_latest
    if yf_getter is None:
        from src.integrations.macro.sources import yfinance_latest
        yf_getter = yfinance_latest

    out: dict[str, Any] = {
        "asof": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "central_bank_rates": {},
        "yields": {},
        "fx": {},
        "commodities": {},
        "_sources": {},
        "_errors": [],
    }

    for group, field, kind, source_id in _FIELDS:
        try:
            if kind == "FRED":
                raw = fred_getter(source_id)
            elif kind == "yfinance":
                raw = yf_getter(source_id)
            else:
                raise RuntimeError(f"unknown source kind {kind!r}")
            value = _safe_float(raw)
            if value is None:
                out[group][field] = None
                out["_errors"].append({
                    "field": field, "source": f"{kind}:{source_id}",
                    "reason": "non-numeric / NaN response",
                })
            else:
                out[group][field] = value
        except Exception as exc:
            out[group][field] = None
            out["_errors"].append({
                "field": field, "source": f"{kind}:{source_id}",
                "reason": str(exc),
            })
        out["_sources"][field] = f"{kind}:{source_id}"

    # Computed: 2s10s spread in basis points (10y - 2y) * 100, when both present.
    y2 = out["yields"].get("ust_2y")
    y10 = out["yields"].get("ust_10y")
    out["yields"]["us_2s10s_bp"] = round((y10 - y2) * 100) if (y2 is not None and y10 is not None) else None

    return out
```

Create `agent/src/integrations/macro/__init__.py`:

```python
"""Macro snapshot — central-bank rates, yields, FX, commodities."""

from src.integrations.macro.snapshot import fetch_macro_snapshot

__all__ = ["fetch_macro_snapshot"]
```

- [ ] **Step 5: Run — verify pass**

```bash
/tmp/venv/bin/pytest agent/tests/test_macro_snapshot.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add agent/src/integrations/macro/__init__.py agent/src/integrations/macro/sources.py agent/src/integrations/macro/snapshot.py agent/tests/test_macro_snapshot.py
git commit -m "$(cat <<'EOF'
feat(macro): macro_snapshot data fetcher (FRED + yfinance, partial-failure tolerant)

Adds the fetch_macro_snapshot() pure orchestrator plus thin getters for
the FRED public CSV endpoint (no API key) and yfinance. Tests stub the
getters so unit tests run without network. Partial-failure design: any
single source going down leaves its field null and adds a structured
entry to _errors; the snapshot is never raised.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: MCP tool wrapper + cache

**Files:**
- Create: `agent/src/tools/macro_snapshot_tool.py`
- Create: `agent/src/integrations/macro/README.md`
- Test: `agent/tests/test_macro_snapshot_tool_contract.py`

> The cache reuses the existing `SnapshotCache` from
> `agent/src/integrations/indmoney/cache.py`. We DO NOT duplicate it —
> import and reuse. The cache is broker-agnostic; only its location
> (`agent/uploads/<scope>/`) varies, controlled by the `CACHE_DIR_NAME`
> module constant.

> **Cache reuse note:** `SnapshotCache.CACHE_DIR_NAME` is a module-level
> constant set to ``"indmoney"``. To avoid making INDMoney's cache
> directory hold macro snapshots too, instantiate `SnapshotCache` with a
> ``root`` that already has ``"macro"`` baked in (i.e. write
> ``cache.dir`` semantics ourselves at the tool level rather than relying
> on `CACHE_DIR_NAME`). This keeps INDMoney's cache untouched and
> isolates macro snapshots under ``agent/uploads/macro/``.

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_macro_snapshot_tool_contract.py`:

```python
"""End-to-end contract tests for MacroSnapshotTool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))


def _stub_snapshot() -> dict:
    return {
        "asof": "2026-05-09T14:30:00+00:00",
        "central_bank_rates": {"fed_funds_target_upper": 5.50,
                                "fed_funds_target_lower": 5.25},
        "yields": {"ust_2y": 4.81, "ust_10y": 4.34, "us_2s10s_bp": -47},
        "fx": {"usd_inr": 83.45, "dxy": 104.21},
        "commodities": {"gold_usd_oz": 2310.50},
        "_sources": {"fed_funds_target_upper": "FRED:DFEDTARU"},
        "_errors": [],
    }


def test_macro_snapshot_tool_happy_path(monkeypatch):
    """Fresh fetch returns ok=True, structured payload, snapshot_path exists."""
    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot",
        lambda **kw: _stub_snapshot(),
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    out = json.loads(MacroSnapshotTool().execute(force_refresh=True))
    assert out["ok"] is True
    assert out["from_cache"] is False
    assert out["fx"]["usd_inr"] == 83.45
    assert out["yields"]["us_2s10s_bp"] == -47
    assert Path(out["snapshot_path"]).exists()


def test_macro_snapshot_tool_uses_cache_within_ttl(monkeypatch):
    """Second call within TTL returns from_cache=True and never calls fetcher."""
    calls = {"n": 0}

    def counting_fetch(**kw):
        calls["n"] += 1
        return _stub_snapshot()

    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot", counting_fetch,
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    tool = MacroSnapshotTool()
    a = json.loads(tool.execute(force_refresh=True))
    b = json.loads(tool.execute())
    assert calls["n"] == 1
    assert a["from_cache"] is False
    assert b["from_cache"] is True
    assert b["fx"]["usd_inr"] == 83.45


def test_macro_snapshot_tool_force_refresh_skips_cache(monkeypatch):
    calls = {"n": 0}

    def counting_fetch(**kw):
        calls["n"] += 1
        return _stub_snapshot()

    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot", counting_fetch,
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    tool = MacroSnapshotTool()
    tool.execute(force_refresh=True)
    tool.execute(force_refresh=True)
    assert calls["n"] == 2


def test_macro_snapshot_tool_surfaces_errors(monkeypatch):
    """If the snapshot has _errors, they appear in the response unchanged."""
    payload = _stub_snapshot()
    payload["_errors"] = [
        {"field": "ecb_deposit", "source": "FRED:ECBDFR", "reason": "503"},
    ]
    monkeypatch.setattr(
        "src.tools.macro_snapshot_tool.fetch_macro_snapshot", lambda **kw: payload,
    )
    from src.tools.macro_snapshot_tool import MacroSnapshotTool

    out = json.loads(MacroSnapshotTool().execute(force_refresh=True))
    assert out["ok"] is True
    assert len(out["_errors"]) == 1
    assert out["_errors"][0]["field"] == "ecb_deposit"
```

- [ ] **Step 2: Run — verify failure**

```bash
/tmp/venv/bin/pytest agent/tests/test_macro_snapshot_tool_contract.py -v
```

Expected: ImportError on `MacroSnapshotTool`.

- [ ] **Step 3: Implement the tool**

Create `agent/src/tools/macro_snapshot_tool.py`:

```python
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
```

Create `agent/src/integrations/macro/README.md`:

```markdown
# Macro snapshot integration

Read-only data fetcher for the cross-asset macro state — central-bank
rates, US Treasury yields, FX, commodities. Powers the
`macro_snapshot` MCP tool and the `macro-rates-fx-analysis` recipe
skill.

## Sources (no API keys required)

| Field group | Source | Endpoint |
|---|---|---|
| Central-bank rates | FRED public CSV | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>` |
| US Treasury yields | FRED public CSV | same |
| FX | yfinance | `^TICKER` / `=X` symbols |
| Commodities | yfinance | futures contracts (`BZ=F`, `CL=F`, `GC=F`) |

Per-field source mapping is in `agent/src/integrations/macro/snapshot.py::_FIELDS`.

## Failure handling

`fetch_macro_snapshot()` never raises. If a single source fails:
- The corresponding field becomes `null`
- A structured entry lands in `_errors` with `{field, source, reason}`
- All other fields keep their values

The MCP tool surfaces `_errors` to the caller so an agent can decide
whether to proceed or escalate.

## Cache

Snapshots are written to `agent/uploads/macro/snapshot.json` with a
1-hour TTL by default (override with `MACRO_SNAPSHOT_TTL_SECONDS`).
The cache is single-file and atomic (temp file + rename).
```

- [ ] **Step 4: Run — verify pass**

```bash
/tmp/venv/bin/pytest agent/tests/test_macro_snapshot_tool_contract.py -v
```

Expected: 4 passed.

Then re-run all macro tests:

```bash
/tmp/venv/bin/pytest agent/tests/test_macro_snapshot.py agent/tests/test_macro_snapshot_tool_contract.py -q
```

Expected: 7 passed (3 + 4).

- [ ] **Step 5: Commit**

```bash
git add agent/src/tools/macro_snapshot_tool.py agent/src/integrations/macro/README.md agent/tests/test_macro_snapshot_tool_contract.py
git commit -m "$(cat <<'EOF'
feat(macro): MacroSnapshotTool with TTL cache

Wraps fetch_macro_snapshot() in a BaseTool subclass with a 1-hour
single-file cache under agent/uploads/macro/snapshot.json (TTL
configurable via MACRO_SNAPSHOT_TTL_SECONDS). Auto-registers in the
agent tool registry via __subclasses__() discovery; MCP exposure is
in the next commit. Contract tests stub fetch_macro_snapshot at the
tool layer so they run without network.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: MCP wrapper for macro_snapshot

**Files:**
- Modify: `agent/mcp_server.py` — add one `@mcp.tool` wrapper before the "Entry point" section
- Test: append a regression assertion to `agent/tests/test_indmoney_registry.py`

> **Why a single wrapper here:** the indmoney registry test
> (`test_indmoney_tools_exposed_via_fastmcp_surface`) is the canonical
> guard against the false-positive bug we hit on the indmoney v2 PR —
> registry membership ≠ MCP exposure. Extending it to also assert
> `macro_snapshot` is on the FastMCP surface keeps that guard
> centralised and prevents a similar regression for this tool.

- [ ] **Step 1: Modify the registry test (failing-test first)**

Edit `agent/tests/test_indmoney_registry.py`. Replace the
`test_indmoney_tools_exposed_via_fastmcp_surface` test with a version
that also asserts `macro_snapshot` is exposed:

```python
def test_indmoney_and_macro_tools_exposed_via_fastmcp_surface():
    """REGRESSION GUARD: assert the FastMCP server actually advertises the
    INDMoney tools AND the macro_snapshot tool. The earlier version of
    this test only checked the in-process agent registry, which let the
    indmoney v2 PR ship without @mcp.tool wrappers. ``mcp.list_tools()``
    is the public FastMCP API and matches what an MCP client (e.g.
    Claude Code via vibe-trading-mcp) actually sees on tools/list.
    """
    mcp_module = importlib.import_module("mcp_server")
    tools = asyncio.run(mcp_module.mcp.list_tools())
    names = {t.name for t in tools}
    expected = _INDMONEY_TOOLS | {"macro_snapshot"}
    assert expected <= names, (
        f"Required tools missing from FastMCP surface. Saw: {sorted(names)}"
    )
    # Sanity: dropped transactions tool must NOT have re-appeared.
    assert "indmoney_transactions" not in names
```

- [ ] **Step 2: Run — verify failure**

```bash
/tmp/venv/bin/pytest agent/tests/test_indmoney_registry.py::test_indmoney_and_macro_tools_exposed_via_fastmcp_surface -v
```

Expected: FAIL with "Required tools missing... 'macro_snapshot' not in names".

- [ ] **Step 3: Add the @mcp.tool wrapper**

In `agent/mcp_server.py`, find the section divider just before
`# Entry point` (around line 750+ after the indmoney section). Insert
a new section above it:

```python
# ---------------------------------------------------------------------------
# Macro snapshot tool
# ---------------------------------------------------------------------------
#
# Wrapper around the agent-side MacroSnapshotTool. As with the indmoney
# tools, agent-registry membership alone does not expose a tool over MCP —
# this @mcp.tool decorator is what makes macro_snapshot callable from
# Claude Code / Cursor / Claude Desktop via vibe-trading-mcp. See
# docs/superpowers/specs/2026-05-09-mcp-llm-boundary-design.md for the
# integration overview and agent/src/integrations/macro/README.md for
# data sources + failure handling.

@mcp.tool
def macro_snapshot(force_refresh: bool = False) -> str:
    """Pull a current cross-asset macro snapshot.

    Returns central-bank policy rates (Fed/ECB/BoE), US Treasury yields
    (2Y/10Y/30Y) + 2s10s spread, FX (USD/INR, DXY, EUR/USD, USD/JPY),
    and commodity benchmarks (Brent, WTI, gold). Sources are FRED public
    CSV + yfinance — no API keys required. Cache TTL is 1 hour; pass
    force_refresh=true to skip. Partial-failure tolerant: a missing
    source surfaces in the _errors array while other fields stay
    populated.

    Args:
        force_refresh: Skip the TTL cache and re-fetch from upstream.
    """
    registry = _get_registry()
    return registry.execute("macro_snapshot", {"force_refresh": force_refresh})
```

- [ ] **Step 4: Run — verify pass**

```bash
/tmp/venv/bin/pytest agent/tests/test_indmoney_registry.py -v
```

Expected: all tests pass; the renamed test now asserts both indmoney + macro tools are exposed.

Then check the FastMCP tool count climbed to 25:

```bash
/tmp/venv/bin/python -c "
import sys, asyncio, importlib
sys.path.insert(0, 'agent')
m = importlib.import_module('mcp_server')
tools = asyncio.run(m.mcp.list_tools())
print('count:', len(tools))
print('macro_snapshot:', any(t.name == 'macro_snapshot' for t in tools))
"
```

Expected:
```
count: 25
macro_snapshot: True
```

- [ ] **Step 5: Commit**

```bash
git add agent/mcp_server.py agent/tests/test_indmoney_registry.py
git commit -m "$(cat <<'EOF'
feat(mcp): expose macro_snapshot via @mcp.tool

Adds the FastMCP wrapper for MacroSnapshotTool (count goes 24 → 25).
Mirrors the indmoney_holdings/indmoney_sync wrapper pattern: thin
delegate to _get_registry().execute(), with the docstring carrying
the agent-facing description.

Extends the registry regression guard to assert both indmoney_* and
macro_snapshot are on the FastMCP surface — same false-positive bug
class that indmoney v2 hit (registry membership ≠ MCP exposure)
applies here, and the centralised test catches it for any future
@mcp.tool we add.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Three recipe skills + skills.py one-liner

**Files:**
- Create: `agent/src/skills/macro-rates-fx-analysis/SKILL.md`
- Create: `agent/src/skills/portfolio-rebalance/SKILL.md`
- Create: `agent/src/skills/equity-fundamental-deep-dive/SKILL.md`
- Modify: `agent/src/agent/skills.py` — append `"recipe"` to `_CATEGORY_ORDER`
- Test: `agent/tests/test_recipe_skills_loadable.py`

> **Note on the protected-modules rule:** `agent/src/agent/` is listed in
> CLAUDE.md as a protected module ("ask before non-trivial changes").
> Appending one string to a display-order tuple is trivial — no logic
> change. The change is documented in the spec and explicitly approved
> there.

- [ ] **Step 1: Write the failing test**

Create `agent/tests/test_recipe_skills_loadable.py`:

```python
"""Verify the three recipe skills are discoverable and well-formed."""

from __future__ import annotations


_RECIPE_SKILLS = {
    "macro-rates-fx-analysis",
    "portfolio-rebalance",
    "equity-fundamental-deep-dive",
}


def test_recipe_skills_are_loaded():
    """SkillsLoader picks up all three recipe SKILL.md files."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    names = {s.name for s in loader.skills}
    assert _RECIPE_SKILLS <= names, (
        f"Missing recipe skills: {_RECIPE_SKILLS - names}"
    )


def test_recipe_skills_have_recipe_category():
    """All three skills declare category: recipe in their frontmatter."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    by_name = {s.name: s for s in loader.skills}
    for name in _RECIPE_SKILLS:
        assert by_name[name].category == "recipe", (
            f"{name} has category={by_name[name].category!r}, expected 'recipe'"
        )


def test_recipe_category_in_display_order():
    """The 'recipe' category renders before 'other' in grouped output."""
    from src.agent.skills import SkillsLoader

    order = SkillsLoader._CATEGORY_ORDER
    assert "recipe" in order, "_CATEGORY_ORDER missing 'recipe'"
    assert order.index("recipe") < order.index("other"), (
        "'recipe' must render before 'other' in grouped skill display"
    )


def test_recipe_load_skill_returns_full_body():
    """list_skills + load_skill round-trip via the project's helpers."""
    from src.agent.skills import SkillsLoader

    loader = SkillsLoader()
    body = loader.get_content("macro-rates-fx-analysis")
    assert "macro_snapshot" in body, (
        "Recipe body must reference the macro_snapshot tool to be useful"
    )
    assert body.startswith("---") or "When to use" in body, (
        "Recipe body must contain frontmatter or a When-to-use heading"
    )
```

- [ ] **Step 2: Run — verify failure**

```bash
/tmp/venv/bin/pytest agent/tests/test_recipe_skills_loadable.py -v
```

Expected: 4 failures (skills not present, "recipe" not in `_CATEGORY_ORDER`).

- [ ] **Step 3: Update `_CATEGORY_ORDER`**

In `agent/src/agent/skills.py`, find:

```python
    _CATEGORY_ORDER = [
        "data-source", "strategy", "analysis", "asset-class",
        "crypto", "flow", "tool", "other",
    ]
```

Replace with:

```python
    _CATEGORY_ORDER = [
        "data-source", "strategy", "analysis", "asset-class",
        "crypto", "flow", "tool", "recipe", "other",
    ]
```

- [ ] **Step 4: Create the macro recipe**

Create `agent/src/skills/macro-rates-fx-analysis/SKILL.md`:

```markdown
---
name: macro-rates-fx-analysis
description: Synthesise a cross-asset macro view (rates, FX, commodities) from current data. Replaces the macro_rates_fx_desk swarm preset for single-LLM (e.g. Claude Code via MCP) orchestration — no separate LLM provider needed.
category: recipe
---

# Macro / Rates / FX analysis recipe

## When to use

- User asks for a macro backdrop, rate trajectory, FX positioning, or asset-allocation implications of current macro conditions.
- The `macro_rates_fx_desk` swarm preset would otherwise be the path; this recipe replaces it with single-LLM orchestration so you don't need a `LANGCHAIN_PROVIDER` env var.

## Inputs

None — operates on current global macro state. Optional: pass the user's portfolio context if they've shared it (e.g. via `indmoney_holdings`) so the asset-allocation section can be specific.

## Steps

### 1. Pull current data

Call MCP tool `macro_snapshot()`. If `_errors` is non-empty, surface the affected fields to the user before continuing — partial data is OK but do not silently hide it.

### 2. Pull recent central-bank communications (parallel)

Call `web_search` for each of the following with `max_results=5`:
- "Fed FOMC statement <CURRENT_MONTH> <CURRENT_YEAR>"
- "RBI MPC <CURRENT_MONTH> <CURRENT_YEAR>"
- "ECB rate decision <CURRENT_MONTH> <CURRENT_YEAR>"

Skim for actual policy moves vs commentary; cite source URLs in the final output.

### 3. (Optional) Pull the user's portfolio shape

If the user is asking specifically about implications for their portfolio, call `indmoney_holdings()` to get current allocation. Otherwise skip.

### 4. Synthesise

Produce a markdown report:

- **One-sentence macro stance** — e.g. "Cautiously risk-on with USD-strength tailwinds" or "Defensive, recession risk rising".
- **Rate trajectory** — where each major CB sits, market-implied path, divergence signals (e.g. Fed cutting while RBI holds → INR strength).
- **Yield curve dynamics** — US 2s10s level (from `yields.us_2s10s_bp`), what the curve is pricing.
- **FX positioning** — USD strength via DXY, USD/INR direction, EUR / JPY context.
- **Commodity signals** — oil and gold as inflation / risk proxies; gold's ratio to real yields.
- **Asset-allocation implications** — what this combination favours or argues against. If you have the user's portfolio, name specific over/underweights to consider.

### 5. Cite provenance

Every numeric claim from `macro_snapshot` should reference the `_sources` field (e.g. "*Fed funds upper at 5.50% (FRED:DFEDTARU)*"). This lets the user audit.

## Failure modes

- If `macro_snapshot` returns mostly nulls (more than half of fields in `_errors`), do **not** synthesise. Surface the data-quality problem and stop.
- If `web_search` is unreachable, proceed without it but flag the recency gap in the macro stance line.
```

- [ ] **Step 5: Create the rebalance recipe**

Create `agent/src/skills/portfolio-rebalance/SKILL.md`:

```markdown
---
name: portfolio-rebalance
description: Performance attribution + concentration analysis + rebalance recommendation for the user's INDMoney portfolio. Replaces the portfolio_review_board swarm preset for single-LLM orchestration via MCP.
category: recipe
---

# Portfolio rebalance recipe

## When to use

- User asks "should I rebalance?", "is my portfolio concentrated?", "give me target weights", or any variation that wants both diagnostics and a proposed action.

## Inputs

- INDMoney holdings, fetched automatically via `indmoney_holdings()`.
- Optional: user-stated target allocation (e.g. "60/40 equity/bond"). If absent, propose one based on the macro context.

## Steps

### 1. Pull current holdings

Call MCP tool `indmoney_holdings()`. If `error_kind` is `needs_auth` or `stale_token`, instruct the user to run `python scripts/indmoney_oauth.py` and stop. Otherwise capture:
- `holdings[]` — per-position rows
- `totals` — `total_invested`, `total_current_value`, `total_networth`
- `assets_by_class` — for the per-class allocation
- `cash` — for the liquid bucket

### 2. Pull macro context

Call MCP tool `macro_snapshot()`. Use it only to inform the rebalance recommendation (e.g. "with 2s10s inverted, defensive tilt is reasonable") — do not turn this into a full macro report.

### 3. Compute concentration metrics

- **Top-N concentration** — share of `total_current_value` held by the top 5 positions.
- **Per-asset-class allocation** — pull from `assets_by_class[].progress_value_percentage`.
- **Single-position max weight** — flag any holding > 10% of `total_current_value`.

### 4. Compare to target allocation

If the user gave a target, compute the gap per asset class. If they didn't, propose a target based on:
- Current macro stance (from step 2)
- Their realised return vs invested (high return → consider trimming gainers)
- A general principle of capping single-stock weight at 10% and asset-class concentration at ≤65%

### 5. Synthesise

Markdown report:

- **Snapshot** — total invested, current value, return %, position count.
- **Concentration risks** — bullet list: any over-10% positions, any over-65% asset class.
- **Macro context** — one paragraph from step 2.
- **Recommended rebalance** — a table:

  | Asset class | Current % | Target % | Action (INR) |
  |---|---|---|---|

  And per-position trim candidates if the top-N concentration exceeds 60%.
- **Caveat** — INDMoney holdings come back as `investment_code`, not tickers. If the user wants to act on this, they need to map codes to brokerage symbols themselves (or you call `lookup_ind_keys` once that's wired).

## Failure modes

- If `indmoney_holdings()` returns 0 holdings, stop and surface — likely a token / fetch problem.
- If `macro_snapshot()` fails entirely, you can still produce concentration analysis; just skip the macro paragraph.
```

- [ ] **Step 6: Create the equity-fundamental recipe**

Create `agent/src/skills/equity-fundamental-deep-dive/SKILL.md`:

```markdown
---
name: equity-fundamental-deep-dive
description: Single-ticker fundamental + valuation + quality assessment culminating in a buy/hold/sell view. Replaces the fundamental_research_team swarm preset for single-LLM orchestration via MCP, one ticker at a time.
category: recipe
---

# Equity fundamental deep-dive recipe

## When to use

- User names one ticker and asks for fundamentals, valuation, "should I hold this", earnings outlook, or a buy/hold/sell call.
- Use one invocation per ticker — looping over many positions is the user's call to make.

## Inputs

- Ticker symbol (required) — e.g. `DOCN`, `STX`, `INFY.NS`, `RELIANCE.NS`. The recipe does not auto-discover from the user's holdings (`Holding.symbol` is INDMoney's `investment_code`, not a ticker — see `docs/indmoney.md`).

## Steps

### 1. Pull market-data context

Call MCP tool `get_market_data` for the ticker over the last 1 year (daily). This gives you price action, current price, 52-week range.

### 2. Pull fundamentals via web search

Call `web_search` for each of (parallel):
- "<TICKER> latest earnings revenue growth"
- "<TICKER> P/E P/B ROE 2026"
- "<TICKER> analyst consensus target"
- "<TICKER> latest 10-K key risks"

`max_results=5` each. Prefer SEC EDGAR, official IR pages, mainstream financial news.

### 3. Pull macro context (lightweight)

Call MCP tool `macro_snapshot()`. Use for: rate environment (matters for high-multiple stocks) and FX (for ADRs / Indian equities held by foreign investors).

### 4. Optional: factor analysis

If the user wants quant context and the ticker is in a market the project's `factor_analysis` tool covers, call it. Otherwise skip — this recipe is qualitative-leaning.

### 5. Synthesise

Markdown report with these sections, in order:

- **Headline** — One-sentence buy/hold/sell call with conviction qualifier (e.g. "Hold — fairly valued with binary catalyst risk").
- **Business** — What the company does. One paragraph.
- **Financials** — Revenue trend (3 years), EPS trend, margins, debt levels.
- **Valuation** — Current P/E, P/B, EV/EBITDA vs sector and own 5y history. Highlight any extreme dispersion.
- **Quality** — ROE, ROIC, FCF conversion, balance-sheet strength.
- **Catalysts** — Upcoming earnings date, product launches, regulatory items.
- **Risks** — Top 2-3 from the latest 10-K or analyst notes.
- **Macro overlay** — One paragraph: how does the current macro environment (from `macro_snapshot`) help or hurt this name?
- **Verdict** — Restate the headline with confidence rationale and any conditional logic ("buy on a 10% pullback to <price>", etc.).

### 6. Cite

Every claim from a numeric source must cite — `_sources` field for `macro_snapshot`, the `web_search` URLs for fundamentals.

## Failure modes

- If `get_market_data` fails for the ticker (e.g. unsupported market), continue without price action but flag it.
- If web search returns nothing useful for a tiny / private-adjacent ticker, surface that and recommend the user provide the latest filing themselves.
```

- [ ] **Step 7: Run — verify pass**

```bash
/tmp/venv/bin/pytest agent/tests/test_recipe_skills_loadable.py -v
```

Expected: 4 passed.

Then verify nothing else regressed:

```bash
/tmp/venv/bin/pytest --ignore=agent/tests/e2e_backtest -q 2>&1 | tail -3
```

Expected: 906 passed (current 895 + 3 from `test_macro_snapshot.py` + 4 from `test_macro_snapshot_tool_contract.py` + 4 from `test_recipe_skills_loadable.py`). The indmoney registry test was renamed in-place (not added/removed), so the count change is purely additive.

- [ ] **Step 8: Commit**

```bash
git add agent/src/skills/macro-rates-fx-analysis agent/src/skills/portfolio-rebalance agent/src/skills/equity-fundamental-deep-dive agent/src/agent/skills.py agent/tests/test_recipe_skills_loadable.py
git commit -m "$(cat <<'EOF'
feat(skills): three recipe skills replacing data-heavy swarm presets

* macro-rates-fx-analysis  → replaces macro_rates_fx_desk
* portfolio-rebalance      → replaces portfolio_review_board
* equity-fundamental-deep-dive → replaces fundamental_research_team

Each is a SKILL.md tagged category: recipe. The body is a step-by-step
sequence of MCP tool calls (macro_snapshot, indmoney_holdings,
web_search, get_market_data) that Claude Code orchestrates with one
LLM voice — no LANGCHAIN_PROVIDER env var required.

Adds "recipe" to SkillsLoader._CATEGORY_ORDER so the new category
renders before "other" in grouped skill displays. Loader test asserts
all three are discovered and tagged correctly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: CLAUDE.md boundary section + feature matrix doc

**Files:**
- Modify: `CLAUDE.md` — add "MCP / LLM boundary" subsection inside Architecture, after "Skill namespaces"
- Create: `docs/mcp-feature-matrix.md`

- [ ] **Step 1: Add the MCP/LLM boundary section to CLAUDE.md**

Find the line after the "Skill namespaces" section ends (it ends with the paragraph starting "If you are an MCP-client agent and need a project skill..."). Just before the next section header (`## Project conventions`), insert:

```markdown
### MCP / LLM boundary (when does a tool need a separate LLM?)

Most `vibe-trading-mcp` tools are pure compute or data-fetch and work with no LLM provider configured — Claude Code (the MCP client) is the only LLM in the loop. The exception is `run_swarm`, whose workers spawn their own `ChatLLM` (`agent/src/swarm/worker.py:225`) and require `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY` env vars to function.

| Tool / preset family | Needs LLM creds? | How to invoke from Claude Code |
|---|---|---|
| Data + math tools (`macro_snapshot`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `backtest`, `analyze_trade_journal`, `indmoney_holdings`, `indmoney_sync`, etc.) | No | Direct MCP tool call |
| Recipe skills (skills with `category: recipe` in their SKILL.md frontmatter) | No | `load_skill(name="<recipe-name>")`, then follow steps |
| Data-heavy swarm presets (`macro_rates_fx_desk`, `portfolio_review_board`, `fundamental_research_team`, etc.) | Yes (workers each call ChatLLM) | **Prefer the corresponding recipe skill if one exists.** Fall back to `run_swarm` only after setting `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY`. |
| Adversarial / multi-voice presets (`investment_committee`, `geopolitical_war_room`, `event_driven_task_force`, `sentiment_intelligence_team`, `social_alpha_team`) | Yes | These genuinely need multi-voice debate; recipes can't replicate them. Set the env vars to opt in. |

Recipe skills are the canonical replacement for data-heavy swarm presets when running via MCP. See [`docs/mcp-feature-matrix.md`](docs/mcp-feature-matrix.md) for the full preset → recipe mapping (filled in over time as recipes are added).
```

- [ ] **Step 2: Create the feature-matrix companion doc**

Create `docs/mcp-feature-matrix.md`:

```markdown
# MCP feature matrix (preset → recipe mapping)

Tracks which swarm presets have a recipe-skill replacement (works via MCP
without a second LLM) vs which still require a configured LLM provider.

## Status legend

- 🟢 **MCP-ready** — has a recipe skill, no LLM creds required.
- 🟡 **Pending** — could be replaced by a recipe in principle; not yet written.
- 🔴 **Swarm-only** — genuinely needs multi-voice adversarial debate; recipe replacement is not on the roadmap. Set `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY` to opt in.

## Mapping

| Preset | Status | Recipe skill |
|---|---|---|
| `macro_rates_fx_desk` | 🟢 | `macro-rates-fx-analysis` |
| `portfolio_review_board` | 🟢 | `portfolio-rebalance` |
| `fundamental_research_team` | 🟢 (single ticker) | `equity-fundamental-deep-dive` |
| `equity_research_team` | 🟡 | — |
| `factor_research_committee` | 🟡 | — |
| `ml_quant_lab` | 🟡 | — |
| `pairs_research_lab` | 🟡 | — |
| `statistical_arbitrage_desk` | 🟡 | — |
| `technical_analysis_panel` | 🟡 | — |
| `risk_committee` | 🟡 | — |
| `etf_allocation_desk` | 🟡 | — |
| `earnings_research_desk` | 🟡 | — |
| `sector_rotation_team` | 🟡 | — |
| `credit_research_team` | 🟡 | — |
| `convertible_bond_team` | 🟡 | — |
| `commodity_research_team` | 🟡 | — |
| `fund_selection_panel` | 🟡 | — |
| `quant_strategy_desk` | 🟡 | — |
| `derivatives_strategy_desk` | 🟡 | — |
| `global_equities_desk` | 🟡 | — |
| `global_allocation_committee` | 🟡 | — |
| `macro_strategy_forum` | 🟡 | — |
| `crypto_research_lab` | 🟡 | — |
| `crypto_trading_desk` | 🟡 | — |
| `investment_committee` | 🔴 | (multi-voice debate — opt in to swarm) |
| `geopolitical_war_room` | 🔴 | (qualitative synthesis — opt in to swarm) |
| `event_driven_task_force` | 🔴 | (special-situation reasoning — opt in to swarm) |
| `sentiment_intelligence_team` | 🔴 | (news / sentiment interpretation — opt in to swarm) |
| `social_alpha_team` | 🔴 | (social-media interpretation — opt in to swarm) |

## Adding a new recipe

1. Identify the preset's underlying data needs.
2. Confirm an MCP tool exists for each (or add one — see `agent/src/integrations/macro/` for the pattern).
3. Write `agent/src/skills/<recipe-name>/SKILL.md` with `category: recipe`. Body is a step-by-step tool-call sequence + a synthesis prompt.
4. Update the row in this table.
5. Add a regression test in `agent/tests/test_recipe_skills_loadable.py` asserting the new skill loads.
```

- [ ] **Step 3: Run the full project suite**

```bash
/tmp/venv/bin/pytest --ignore=agent/tests/e2e_backtest -q 2>&1 | tail -3
```

Expected: green; total count = current 895 + new tests added in tasks 1-4.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git add -f docs/mcp-feature-matrix.md
git commit -m "$(cat <<'EOF'
docs: MCP / LLM boundary in CLAUDE.md + preset → recipe matrix

CLAUDE.md gains an "MCP / LLM boundary" subsection with a table that
classifies every tool / preset family as either:
  * MCP-only (no LLM creds needed) — most data + math tools, plus any
    skill tagged category: recipe
  * Recipe-replaceable swarm preset (use the recipe instead of run_swarm)
  * Swarm-only adversarial preset (set LANGCHAIN_PROVIDER + PROVIDER_API_KEY)

docs/mcp-feature-matrix.md is the per-preset tracker — three presets are
🟢 MCP-ready today (the three new recipe skills), the data-heavy ones
are 🟡 pending, the five adversarial ones are 🔴 swarm-only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Final lint + full sweep

- [ ] **Step 1: Lint the new code paths**

```bash
ruff check agent/src/integrations/macro agent/src/tools/macro_snapshot_tool.py agent/tests/test_macro_snapshot.py agent/tests/test_macro_snapshot_tool_contract.py agent/tests/test_recipe_skills_loadable.py 2>&1 | tail -10
```

Expected: empty output (no lint errors). If `ruff` isn't on PATH, try `/tmp/venv/bin/ruff` or `python -m ruff`. If still unavailable, note that CI runs ruff so any issues will surface there.

- [ ] **Step 2: Confirm Frontend untouched**

```bash
git diff main..HEAD --stat -- frontend/
```

Expected: empty.

- [ ] **Step 3: Final test sweep**

```bash
/tmp/venv/bin/pytest --ignore=agent/tests/e2e_backtest -q 2>&1 | tail -3
```

Expected: green.

- [ ] **Step 4: Manual smoke against live data**

This is the only step that hits the network. Run from a shell where the project is editable-installed (or use `/tmp/venv/bin/python`):

```bash
/tmp/venv/bin/python -c "
import sys, json
sys.path.insert(0, 'agent')
from src.tools.macro_snapshot_tool import MacroSnapshotTool

out = json.loads(MacroSnapshotTool().execute(force_refresh=True))
print('ok:', out.get('ok'))
print('errors:', len(out.get('_errors', [])))
print('fed_funds_target_upper:', out['central_bank_rates'].get('fed_funds_target_upper'))
print('ust_10y:', out['yields'].get('ust_10y'))
print('us_2s10s_bp:', out['yields'].get('us_2s10s_bp'))
print('usd_inr:', out['fx'].get('usd_inr'))
print('gold_usd_oz:', out['commodities'].get('gold_usd_oz'))
print('snapshot_path:', out.get('snapshot_path'))
"
```

Expected: ok=True, fed funds rate around 5.x, UST 10Y around 4.x, USD/INR around 83, gold around 2300, snapshot_path exists.

If any value is `None`, check `_errors` — that's the partial-failure path working. Note the error pattern in the PR description so future readers know what to expect.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin feat/mcp-llm-boundary
```

Then open the PR at the URL git prints.

---

## Done definition

- [ ] All Task 1-6 commits land green
- [ ] `pytest --ignore=agent/tests/e2e_backtest -q` passes
- [ ] `mcp.list_tools()` returns 25 tools including `macro_snapshot`
- [ ] `list_skills()` returns the three new recipe names with `category: recipe`
- [ ] CLAUDE.md and `docs/mcp-feature-matrix.md` document the boundary
- [ ] One human-driven smoke confirms `MacroSnapshotTool` returns live data with no surprising nulls
- [ ] PR description references the spec and notes which presets remain swarm-only

When all boxes are checked, push the branch and open a PR titled `feat: MCP / LLM boundary — macro_snapshot tool + 3 recipe skills`.
