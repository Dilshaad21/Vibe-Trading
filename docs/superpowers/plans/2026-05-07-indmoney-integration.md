# INDMoney MCP Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull the user's INDMoney US-stocks portfolio (holdings, transactions, cash) into Vibe-Trading via INDMoney's MCP server at `https://mcp.indmoney.com/mcp`, exposing three new agent tools that auto-publish through the existing tool registry to both the ReAct loop and `vibe-trading-mcp`.

**Architecture:** New module `agent/src/integrations/indmoney/` containing an MCP-client wrapper, OAuth token cache, JSON-to-`TradeRecord` normalizer, and a TTL-gated snapshot cache that writes files into `agent/uploads/indmoney/` (already inside `path_utils._default_file_roots()`). Three new `BaseTool` subclasses in `agent/src/tools/` — auto-discovered by `agent/src/tools/__init__.py`. Read-only v1: holdings, transactions, cash; no order placement.

**Tech Stack:** Python 3.11+, `fastmcp>=2.0.0` (already a dep — used as MCP **client** here for the first time in this repo), `httpx` (already a dep, for the OAuth dance), `oauth-cli-kit` (already used by `agent/src/providers/openai_codex.py`), `pandas` (already a dep). Tests use `pytest`. CSV outputs follow the column shape produced by `agent/src/tools/trade_journal_parsers.py::parse_generic`.

**Spec:** [`docs/superpowers/specs/2026-05-07-indmoney-integration-design.md`](../specs/2026-05-07-indmoney-integration-design.md).

**Test command:** Always run with the project's standard pytest invocation:

```bash
pytest --ignore=agent/tests/e2e_backtest --tb=short -q
```

**Commit style:** Conventional Commits (`feat:`, `test:`, `docs:`, `chore:`). Do not skip hooks.

---

## File map

Created (new):
- `agent/src/integrations/__init__.py` — package marker
- `agent/src/integrations/indmoney/__init__.py` — public exports
- `agent/src/integrations/indmoney/errors.py` — `ErrorKind`, `build_error()`
- `agent/src/integrations/indmoney/types.py` — `Holding`, `CashSnapshot`
- `agent/src/integrations/indmoney/normalizer.py` — JSON → types + CSV writers
- `agent/src/integrations/indmoney/cache.py` — snapshot + index + lock
- `agent/src/integrations/indmoney/audit.py` — append-only audit log
- `agent/src/integrations/indmoney/auth.py` — OAuth token cache + refresh
- `agent/src/integrations/indmoney/client.py` — MCP client wrapper
- `agent/src/integrations/indmoney/README.md` — config + manual-test recipe
- `agent/src/tools/indmoney_holdings_tool.py` — `IndMoneyHoldingsTool(BaseTool)`
- `agent/src/tools/indmoney_transactions_tool.py` — `IndMoneyTransactionsTool(BaseTool)`
- `agent/src/tools/indmoney_sync_tool.py` — `IndMoneySyncTool(BaseTool)`
- `agent/tests/test_indmoney_errors.py`
- `agent/tests/test_indmoney_types.py`
- `agent/tests/test_indmoney_normalizer.py`
- `agent/tests/test_indmoney_cache.py`
- `agent/tests/test_indmoney_audit.py`
- `agent/tests/test_indmoney_auth.py`
- `agent/tests/test_indmoney_client.py`
- `agent/tests/test_indmoney_tool_contract.py`
- `agent/tests/test_indmoney_path_safety.py`
- `agent/tests/test_indmoney_secret_leakage.py`
- `agent/tests/test_indmoney_remote_gate.py`
- `agent/tests/test_indmoney_registry.py` — confirms 3 tools register
- `agent/tests/fixtures/indmoney/holdings.json`
- `agent/tests/fixtures/indmoney/transactions.json`
- `agent/tests/fixtures/indmoney/cash.json`
- `agent/tests/fixtures/indmoney/discovery.json`
- `scripts/indmoney_discover.py` — one-shot discovery script (Task 0)
- `docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md` — discovery output (Task 0)

Modified:
- `agent/cli.py` — add `indmoney login` and `indmoney status` subcommands (around line 1747's `_build_parser` and line 1721's `cmd_provider_login` neighborhood)

---

## Task 0: Discovery — confirm INDMoney's actual MCP surface

> **Why first:** Section 11 of the spec flags that the OAuth shape, tool names, input schemas, pagination, and `account_id` semantics at `mcp.indmoney.com/mcp` are unverified assumptions. Coding the normalizer fixtures and auth flow against guessed schemas would burn time. This task produces a discovery notes file the rest of the plan reads from.
>
> **Output:** `docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md` containing the real auth shape, tool list with input/output schemas, sample payloads (sanitized — no real account numbers, no tokens), pagination model, and rate-limit headers. Also a JSON snapshot at `agent/tests/fixtures/indmoney/discovery.json` capturing the raw discovery response.

**Files:**
- Create: `scripts/indmoney_discover.py`
- Create: `docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md`
- Create: `agent/tests/fixtures/indmoney/discovery.json`

- [ ] **Step 1: Write `scripts/indmoney_discover.py`**

```python
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
        # 1. Try OAuth discovery — RFC 8414 well-known endpoint
        oauth_meta = None
        try:
            r = await http.get(url.replace("/mcp", "/.well-known/oauth-authorization-server"))
            if r.status_code == 200:
                oauth_meta = r.json()
        except Exception as exc:
            print(f"[oauth-discovery] {exc}", file=sys.stderr)

        # 2. Try MCP initialize (anonymous) to enumerate tools
        init_payload = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "vibe-trading-discover", "version": "0.0.1"}},
        }
        init_resp = await http.post(url, json=init_payload, headers={"accept": "application/json,text/event-stream"})

        return {
            "oauth_metadata": oauth_meta,
            "initialize_status": init_resp.status_code,
            "initialize_headers": dict(init_resp.headers),
            "initialize_body": _safe_body(init_resp),
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
```

- [ ] **Step 2: Run the script**

```bash
python scripts/indmoney_discover.py
```

Expected outcomes:
- **If OAuth (RFC 8414):** `oauth_metadata` populated with `authorization_endpoint`, `token_endpoint`, `scopes_supported`. Auth flow in this plan stays as-designed.
- **If MCP returns `WWW-Authenticate: Bearer realm=...`:** server uses MCP-flavored OAuth (RFC 9728). Note the realm and token endpoint in the discovery notes.
- **If anonymous `initialize` succeeds:** tool surface is open; static API key (if any) is added per-call.
- **If 401 with no OAuth metadata and no `WWW-Authenticate`:** auth shape is undocumented — STOP. Ask the user how to authenticate before proceeding.

- [ ] **Step 3: Manually authenticate and re-run with token**

If OAuth: complete the browser flow once, capture the `access_token`, then:

```bash
INDMONEY_ACCESS_TOKEN=<your token> python scripts/indmoney_discover.py
```

(extend the script to send `Authorization: Bearer $INDMONEY_ACCESS_TOKEN` if the env-var is set; do this inline in `httpx` headers — do NOT log the token).

- [ ] **Step 4: Run `tools/list`, `tools/call get_holdings`, `tools/call get_transactions`, `tools/call get_account` against the authenticated session**

Capture the responses. Sanitize (replace real account_ids, tokens, symbol holdings with `XXX`-prefixed placeholders) and append to the discovery notes file.

- [ ] **Step 5: Write `docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md`**

Sections to fill in based on what you found:
1. **Auth shape** — OAuth flow, scopes, token TTL, refresh model. If static key, note env-var name expected.
2. **MCP tool list** — names, input schemas, output schemas, pagination model.
3. **Sample payloads (sanitized)** — one each of holdings, transactions, cash.
4. **Rate limits** — observed `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`.
5. **Account semantics** — does one OAuth grant cover US + Indian accounts? Single account_id per token?
6. **Currency on holdings** — USD-only, INR-only, or mixed? Per-line FX or account-level?
7. **Corporate-action representation** — how splits/dividends appear in transactions.
8. **Deltas from spec assumptions** — list every spec assumption that was wrong, and the correction.

- [ ] **Step 6: If discovery surfaces deltas, update the spec inline**

For each delta in section 8 above, edit `docs/superpowers/specs/2026-05-07-indmoney-integration-design.md` and re-commit. Do not silently diverge.

- [ ] **Step 7: Sanitize the fixture and commit**

```bash
# Inspect agent/tests/fixtures/indmoney/discovery.json — replace any tokens, account ids, real symbols
git add scripts/indmoney_discover.py docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md agent/tests/fixtures/indmoney/discovery.json
# Also re-add the spec if it was updated in step 6:
# git add docs/superpowers/specs/2026-05-07-indmoney-integration-design.md
git commit -m "docs(indmoney): discovery notes for mcp.indmoney.com/mcp"
```

---

## Task 1: Package skeleton + error envelope

**Files:**
- Create: `agent/src/integrations/__init__.py`
- Create: `agent/src/integrations/indmoney/__init__.py`
- Create: `agent/src/integrations/indmoney/errors.py`
- Test: `agent/tests/test_indmoney_errors.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_errors.py`:

```python
"""Tests for the INDMoney error envelope."""

from __future__ import annotations

from src.integrations.indmoney.errors import ErrorKind, build_error


def test_build_error_minimum_fields():
    env = build_error(ErrorKind.UPSTREAM_ERROR, "boom")
    assert env == {
        "ok": False,
        "error_kind": "upstream_error",
        "message": "boom",
        "retry_after_seconds": None,
        "auth_url": None,
    }


def test_build_error_rate_limited_includes_retry_after():
    env = build_error(ErrorKind.RATE_LIMITED, "throttled", retry_after_seconds=42)
    assert env["error_kind"] == "rate_limited"
    assert env["retry_after_seconds"] == 42
    assert env["auth_url"] is None


def test_build_error_needs_auth_includes_url():
    env = build_error(ErrorKind.NEEDS_AUTH, "log in", auth_url="https://example/auth")
    assert env["error_kind"] == "needs_auth"
    assert env["auth_url"] == "https://example/auth"


def test_error_kind_values_match_spec():
    assert ErrorKind.NEEDS_AUTH.value == "needs_auth"
    assert ErrorKind.RATE_LIMITED.value == "rate_limited"
    assert ErrorKind.UPSTREAM_ERROR.value == "upstream_error"
    assert ErrorKind.STALE_TOKEN.value == "stale_token"
    assert ErrorKind.CONFIG_MISSING.value == "config_missing"
```

- [ ] **Step 2: Run the test — verify failure**

```bash
pytest agent/tests/test_indmoney_errors.py -v
```

Expected: ImportError (`src.integrations.indmoney.errors` does not exist).

- [ ] **Step 3: Implement**

`agent/src/integrations/__init__.py`:

```python
"""Vibe-Trading integrations with external services."""
```

`agent/src/integrations/indmoney/__init__.py`:

```python
"""INDMoney MCP integration: read-only holdings, transactions, cash."""

from src.integrations.indmoney.errors import ErrorKind, build_error

__all__ = ["ErrorKind", "build_error"]
```

`agent/src/integrations/indmoney/errors.py`:

```python
"""Structured error envelope for INDMoney tool responses.

Every INDMoney tool returns either a success payload or an envelope produced
by ``build_error``. Structured ``error_kind`` values let the agent decide
whether to retry, ask the user, or surface the error — instead of pattern
matching free-form strings.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorKind(str, Enum):
    """Coarse classification of why an INDMoney call failed."""

    NEEDS_AUTH = "needs_auth"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    STALE_TOKEN = "stale_token"
    CONFIG_MISSING = "config_missing"


def build_error(
    kind: ErrorKind,
    message: str,
    *,
    retry_after_seconds: int | None = None,
    auth_url: str | None = None,
) -> dict[str, Any]:
    """Return the canonical INDMoney error envelope."""
    return {
        "ok": False,
        "error_kind": kind.value,
        "message": message,
        "retry_after_seconds": retry_after_seconds,
        "auth_url": auth_url,
    }
```

- [ ] **Step 4: Run the test — verify it passes**

```bash
pytest agent/tests/test_indmoney_errors.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations agent/tests/test_indmoney_errors.py
git commit -m "feat(indmoney): error envelope skeleton"
```

---

## Task 2: Public types — `Holding`, `CashSnapshot`

**Files:**
- Create: `agent/src/integrations/indmoney/types.py`
- Test: `agent/tests/test_indmoney_types.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_types.py`:

```python
"""Tests for INDMoney public types."""

from __future__ import annotations

import pytest

from src.integrations.indmoney.types import CashSnapshot, Holding


def test_holding_is_frozen():
    h = Holding(
        symbol="AAPL", name="Apple Inc",
        quantity=10.0, avg_cost=150.0, market_value=1700.0,
        unrealized_pnl=200.0, currency="USD",
        asset_class="us_equity", asof="2026-05-07T14:30:00+05:30",
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        h.symbol = "MSFT"  # type: ignore[misc]


def test_holding_to_dict_roundtrip():
    h = Holding(
        symbol="AAPL", name="Apple Inc",
        quantity=10.0, avg_cost=150.0, market_value=1700.0,
        unrealized_pnl=200.0, currency="USD",
        asset_class="us_equity", asof="2026-05-07T14:30:00+05:30",
    )
    d = h.to_dict()
    assert d["symbol"] == "AAPL"
    assert d["asset_class"] == "us_equity"
    assert Holding.from_dict(d) == h


def test_cash_snapshot_to_dict_roundtrip():
    c = CashSnapshot(cash_usd=500.0, cash_inr=12000.0, pending_settlement_usd=0.0,
                    asof="2026-05-07T14:30:00+05:30")
    assert CashSnapshot.from_dict(c.to_dict()) == c


def test_holding_asset_class_enum_values():
    # Allowed values per spec section 5.
    for ac in ("us_equity", "us_etf", "indian_equity", "mf"):
        h = Holding(symbol="X", name="x", quantity=1, avg_cost=1, market_value=1,
                    unrealized_pnl=0, currency="USD", asset_class=ac, asof="2026-05-07")
        assert h.asset_class == ac
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_types.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`agent/src/integrations/indmoney/types.py`:

```python
"""Public dataclasses for INDMoney integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Holding:
    """A single open position or cash-equivalent line.

    Attributes:
        symbol: Bare ticker for US equities ("AAPL"); exchange-qualified for
            non-US (".NS" / ".BO" for Indian; etc.).
        name: Human-readable instrument name.
        quantity: Filled quantity (fractional shares supported).
        avg_cost: Cost basis per unit, in ``currency`` (NOT silently
            FX-converted).
        market_value: Current value at fetch time, in ``currency``.
        unrealized_pnl: market_value - quantity*avg_cost, in ``currency``.
        currency: ISO-4217 code ("USD" / "INR").
        asset_class: One of "us_equity" | "us_etf" | "indian_equity" | "mf".
        asof: ISO8601 timestamp from the source.
    """

    symbol: str
    name: str
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    currency: str
    asset_class: str
    asof: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Holding":
        return cls(**d)


@dataclass(frozen=True)
class CashSnapshot:
    """Account-level cash, native + FX."""

    cash_usd: float
    cash_inr: float
    pending_settlement_usd: float
    asof: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CashSnapshot":
        return cls(**d)
```

Update `agent/src/integrations/indmoney/__init__.py`:

```python
"""INDMoney MCP integration: read-only holdings, transactions, cash."""

from src.integrations.indmoney.errors import ErrorKind, build_error
from src.integrations.indmoney.types import CashSnapshot, Holding

__all__ = ["CashSnapshot", "ErrorKind", "Holding", "build_error"]
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_types.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations/indmoney/types.py agent/src/integrations/indmoney/__init__.py agent/tests/test_indmoney_types.py
git commit -m "feat(indmoney): Holding and CashSnapshot dataclasses"
```

---

## Task 3: Normalizer — JSON → Holding/TradeRecord/events + CSV writers

> **Critical contract:** the trades CSV must round-trip through `agent/src/tools/trade_journal_parsers.py::parse_generic` without `_normalize_side` collapsing rows. That function (lines 124–129) only outputs `"buy"` or `"sell"` — anything else is silently coerced to `"buy"`. The normalizer therefore writes ONLY trades to the trades CSV; dividends and corporate actions go to a sibling events CSV per spec Section 5.

**Files:**
- Create: `agent/src/integrations/indmoney/normalizer.py`
- Create: `agent/tests/fixtures/indmoney/holdings.json`
- Create: `agent/tests/fixtures/indmoney/transactions.json`
- Create: `agent/tests/fixtures/indmoney/cash.json`
- Test: `agent/tests/test_indmoney_normalizer.py`

> **Note:** The fixture payload shapes below are illustrative based on common
> broker patterns. After Task 0, replace with the real shapes from the
> sanitized discovery output. Keep the fixture filenames identical.

- [ ] **Step 1: Write fixtures**

`agent/tests/fixtures/indmoney/holdings.json`:

```json
{
  "account_id": "TEST-ACC-001",
  "asof": "2026-05-07T14:30:00+05:30",
  "positions": [
    {"symbol": "AAPL", "name": "Apple Inc",      "quantity": 10.5, "avg_cost": 150.0, "market_value": 1750.0, "unrealized_pnl": 175.0, "currency": "USD", "instrument_type": "equity"},
    {"symbol": "VOO",  "name": "Vanguard S&P500", "quantity": 5.0,  "avg_cost": 400.0, "market_value": 2100.0, "unrealized_pnl": 100.0, "currency": "USD", "instrument_type": "etf"},
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "quantity": 2.0, "avg_cost": 2800.0, "market_value": 5800.0, "unrealized_pnl": 200.0, "currency": "INR", "instrument_type": "equity"}
  ]
}
```

`agent/tests/fixtures/indmoney/transactions.json`:

```json
{
  "account_id": "TEST-ACC-001",
  "items": [
    {"datetime": "2026-04-01T10:00:00Z", "symbol": "AAPL", "name": "Apple Inc",
     "type": "buy",  "quantity": 10, "price": 150.0, "amount": 1500.0, "fee": 0.0,
     "currency": "USD", "fx_usd_inr": 83.2},
    {"datetime": "2026-04-15T10:00:00Z", "symbol": "AAPL", "name": "Apple Inc",
     "type": "sell", "quantity": 2,  "price": 165.0, "amount": 330.0,  "fee": 0.5,
     "currency": "USD", "fx_usd_inr": 83.5},
    {"datetime": "2026-04-20T10:00:00Z", "symbol": "AAPL", "name": "Apple Inc",
     "type": "dividend", "quantity": 0, "price": 0.0, "amount": 5.0, "fee": 0.0,
     "currency": "USD", "fx_usd_inr": 83.5},
    {"datetime": "2026-04-25T10:00:00Z", "symbol": "TSLA", "name": "Tesla",
     "type": "split", "quantity": 9, "price": 0.0, "amount": 0.0, "fee": 0.0,
     "currency": "USD", "ratio": "3:1"},
    {"datetime": "2026-04-26T10:00:00Z", "symbol": "FOO", "name": "Foo",
     "type": "weird_thing", "quantity": 1, "price": 1.0, "amount": 1.0, "fee": 0.0,
     "currency": "USD"}
  ]
}
```

`agent/tests/fixtures/indmoney/cash.json`:

```json
{
  "account_id": "TEST-ACC-001",
  "asof": "2026-05-07T14:30:00+05:30",
  "cash_usd": 1234.56,
  "cash_inr": 5000.0,
  "pending_settlement_usd": 100.0
}
```

- [ ] **Step 2: Write the failing test**

`agent/tests/test_indmoney_normalizer.py`:

```python
"""Tests for INDMoney normalizer + CSV writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.integrations.indmoney.normalizer import (
    normalize_cash,
    normalize_holdings,
    normalize_transactions,
    write_events_csv,
    write_trades_csv,
)
from src.integrations.indmoney.types import CashSnapshot, Holding
from src.tools.trade_journal_parsers import (
    TradeRecord,
    load_dataframe,
    parse_generic,
)

FIX = Path(__file__).parent / "fixtures/indmoney"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_normalize_holdings_marks_us_equity_and_etf():
    holdings = normalize_holdings(_load("holdings.json"))
    assert isinstance(holdings, list)
    by_sym = {h.symbol: h for h in holdings}
    assert by_sym["AAPL"].asset_class == "us_equity"
    assert by_sym["VOO"].asset_class == "us_etf"
    assert by_sym["RELIANCE.NS"].asset_class == "indian_equity"
    assert by_sym["AAPL"].currency == "USD"
    assert by_sym["RELIANCE.NS"].currency == "INR"
    assert by_sym["AAPL"].quantity == 10.5  # fractional preserved


def test_normalize_cash_returns_snapshot():
    cash = normalize_cash(_load("cash.json"))
    assert isinstance(cash, CashSnapshot)
    assert cash.cash_usd == 1234.56
    assert cash.cash_inr == 5000.0
    assert cash.pending_settlement_usd == 100.0


def test_normalize_transactions_splits_trades_from_events():
    trades, events = normalize_transactions(_load("transactions.json"))

    assert all(isinstance(t, TradeRecord) for t in trades)
    assert {t.side for t in trades} == {"buy", "sell"}, "non-buy/sell rows must NOT enter trades"
    assert len(trades) == 2  # buy + sell only

    assert len(events) == 3
    kinds = {e["event_type"] for e in events}
    assert kinds == {"dividend", "split", "unknown"}


def test_normalize_transactions_records_fx_in_notes():
    trades, _ = normalize_transactions(_load("transactions.json"))
    aapl_buy = next(t for t in trades if t.side == "buy")
    # The TradeRecord schema does not have a `notes` field; we encode FX
    # inside `name` as a parenthesized suffix to remain schema-compatible.
    assert "fx_usd_inr=83.2" in aapl_buy.name


def test_normalize_us_market_value_is_us():
    trades, _ = normalize_transactions(_load("transactions.json"))
    for t in trades:
        assert t.market == "us"


def test_write_trades_csv_roundtrips_through_parse_generic(tmp_path: Path):
    """Critical contract: trades CSV must NOT be collapsed by _normalize_side."""
    trades, _ = normalize_transactions(_load("transactions.json"))
    csv_path = tmp_path / "trades.csv"
    write_trades_csv(trades, csv_path)

    df = load_dataframe(csv_path)
    parsed = parse_generic(df)

    # Sides preserved (no silent buy-coercion).
    assert {t.side for t in parsed} == {t.side for t in trades}
    assert len(parsed) == len(trades)


def test_write_events_csv_columns(tmp_path: Path):
    _, events = normalize_transactions(_load("transactions.json"))
    csv_path = tmp_path / "events.csv"
    write_events_csv(events, csv_path)

    with csv_path.open() as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == [
        "datetime", "symbol", "event_type", "quantity_delta",
        "cash_delta", "ratio", "currency", "notes",
    ]


def test_write_events_csv_unknown_event_preserves_payload(tmp_path: Path):
    _, events = normalize_transactions(_load("transactions.json"))
    weird = next(e for e in events if e["event_type"] == "unknown")
    assert "weird_thing" in weird["notes"]


def test_normalize_handles_empty_collections():
    assert normalize_holdings({"positions": [], "account_id": "X", "asof": ""}) == []
    trades, events = normalize_transactions({"items": [], "account_id": "X"})
    assert trades == []
    assert events == []
```

- [ ] **Step 3: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_normalizer.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement**

`agent/src/integrations/indmoney/normalizer.py`:

```python
"""Normalize INDMoney MCP responses into Vibe-Trading internal types.

The trades CSV uses the column shape consumed by
``src.tools.trade_journal_parsers.parse_generic``. Per spec Section 5,
non-trade events (dividends, splits, unknown types) are emitted to a
separate events CSV — they MUST NOT enter the trades CSV because
``_normalize_side`` collapses any non-buy/sell value to "buy", which
would corrupt FIFO PnL pairing.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from src.integrations.indmoney.types import CashSnapshot, Holding
from src.tools.trade_journal_parsers import TradeRecord

logger = logging.getLogger(__name__)

_TRADE_TYPES = {"buy", "sell"}
_KNOWN_EVENT_TYPES = {"dividend", "split", "merger", "spinoff", "reverse_split"}

_INDIAN_SUFFIXES = (".NS", ".BO")


def _classify_asset(symbol: str, instrument_type: str) -> str:
    """Map (symbol, instrument_type) → asset_class enum value."""
    s = symbol.upper()
    t = (instrument_type or "").lower()
    if any(s.endswith(suf) for suf in _INDIAN_SUFFIXES):
        return "indian_equity"
    if t == "etf":
        return "us_etf"
    if t in {"mutual_fund", "mf"}:
        return "mf"
    return "us_equity"


def _market_for(symbol: str) -> str:
    """Map symbol → existing TradeRecord market bucket."""
    s = symbol.upper()
    if any(s.endswith(suf) for suf in _INDIAN_SUFFIXES):
        return "other"  # Indian equities not yet a first-class market
    return "us"


def normalize_holdings(payload: dict[str, Any]) -> list[Holding]:
    """Convert an INDMoney holdings response into ``Holding`` objects."""
    asof = str(payload.get("asof", ""))
    out: list[Holding] = []
    for p in payload.get("positions", []):
        out.append(Holding(
            symbol=str(p["symbol"]).upper(),
            name=str(p.get("name", "")),
            quantity=float(p["quantity"]),
            avg_cost=float(p["avg_cost"]),
            market_value=float(p["market_value"]),
            unrealized_pnl=float(p.get("unrealized_pnl", 0.0)),
            currency=str(p.get("currency", "USD")),
            asset_class=_classify_asset(str(p["symbol"]), str(p.get("instrument_type", ""))),
            asof=asof,
        ))
    return out


def normalize_cash(payload: dict[str, Any]) -> CashSnapshot:
    """Convert an INDMoney cash response into a ``CashSnapshot``."""
    return CashSnapshot(
        cash_usd=float(payload.get("cash_usd", 0.0)),
        cash_inr=float(payload.get("cash_inr", 0.0)),
        pending_settlement_usd=float(payload.get("pending_settlement_usd", 0.0)),
        asof=str(payload.get("asof", "")),
    )


def normalize_transactions(
    payload: dict[str, Any],
) -> tuple[list[TradeRecord], list[dict[str, Any]]]:
    """Split an INDMoney transactions response into trades + events.

    Trades go to the FIFO-eligible CSV (only side="buy"|"sell"). Everything
    else (dividends, splits, unknown types) lands in the events list.
    Unknown event types are preserved with the raw payload in ``notes``.
    """
    trades: list[TradeRecord] = []
    events: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        kind = str(item.get("type", "")).lower()
        symbol = str(item.get("symbol", "")).upper()
        dt = str(item.get("datetime", ""))
        currency = str(item.get("currency", "USD"))

        if kind in _TRADE_TYPES:
            fx = item.get("fx_usd_inr")
            name = str(item.get("name", ""))
            if fx is not None:
                name = f"{name} (fx_usd_inr={fx})"
            trades.append(TradeRecord(
                datetime=dt,
                symbol=symbol,
                name=name,
                side=kind,
                quantity=float(item.get("quantity", 0.0)),
                price=float(item.get("price", 0.0)),
                amount=float(item.get("amount", 0.0)),
                fee=float(item.get("fee", 0.0)),
                market=_market_for(symbol),
            ))
            continue

        event_type = kind if kind in _KNOWN_EVENT_TYPES else "unknown"
        if event_type == "unknown":
            logger.warning("indmoney: unknown transaction type %r — emitting to events CSV", kind)
        events.append({
            "datetime": dt,
            "symbol": symbol,
            "event_type": event_type,
            "quantity_delta": float(item.get("quantity", 0.0)),
            "cash_delta": float(item.get("amount", 0.0)),
            "ratio": str(item.get("ratio", "")),
            "currency": currency,
            "notes": "" if event_type != "unknown" else f"raw_type={kind}; raw={item!r}",
        })
    return trades, events


_TRADES_HEADER = ["datetime", "symbol", "name", "side",
                  "quantity", "price", "amount", "fee", "market"]

_EVENTS_HEADER = ["datetime", "symbol", "event_type", "quantity_delta",
                  "cash_delta", "ratio", "currency", "notes"]


def write_trades_csv(trades: list[TradeRecord], path: Path) -> None:
    """Write trades to a generic-format CSV consumable by parse_generic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_TRADES_HEADER)
        for t in trades:
            w.writerow([t.datetime, t.symbol, t.name, t.side,
                        t.quantity, t.price, t.amount, t.fee, t.market])


def write_events_csv(events: list[dict[str, Any]], path: Path) -> None:
    """Write events (dividends, splits, unknowns) to a sibling CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_EVENTS_HEADER)
        for e in events:
            w.writerow([e["datetime"], e["symbol"], e["event_type"],
                        e["quantity_delta"], e["cash_delta"],
                        e["ratio"], e["currency"], e["notes"]])
```

- [ ] **Step 5: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_normalizer.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add agent/src/integrations/indmoney/normalizer.py agent/tests/test_indmoney_normalizer.py agent/tests/fixtures/indmoney/
git commit -m "feat(indmoney): normalizer with trades/events split"
```

---

## Task 4: Cache + index + concurrent-fetch lock

**Files:**
- Create: `agent/src/integrations/indmoney/cache.py`
- Test: `agent/tests/test_indmoney_cache.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_cache.py`:

```python
"""Tests for the INDMoney snapshot cache, index, and lock."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.integrations.indmoney.cache import (
    CACHE_DIR_NAME,
    SnapshotCache,
)


@pytest.fixture()
def cache(tmp_path: Path) -> SnapshotCache:
    return SnapshotCache(root=tmp_path)


def test_cache_dir_under_root(cache: SnapshotCache, tmp_path: Path):
    assert cache.dir == tmp_path / CACHE_DIR_NAME
    cache.dir.mkdir(parents=True, exist_ok=True)
    assert cache.dir.is_dir()


def test_put_and_get_within_ttl(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"hello": "world"}, ttl_seconds=60)
    fresh = cache.get("acct1", "holdings", "k")
    assert fresh is not None
    assert fresh["hello"] == "world"


def test_get_returns_none_after_ttl(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"x": 1}, ttl_seconds=0)
    time.sleep(0.05)
    assert cache.get("acct1", "holdings", "k") is None


def test_force_refresh_skips_cache(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"v": 1}, ttl_seconds=60)
    assert cache.get("acct1", "holdings", "k", force_refresh=True) is None


def test_corrupt_index_is_rebuilt_from_disk(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"v": 1}, ttl_seconds=60)
    (cache.dir / ".index.json").write_text("{not json")
    # Should not raise; rebuilds with no entries (raw files still exist).
    cache._load_index()  # private but tested
    assert isinstance(cache._index, dict)


def test_lock_is_released_on_exit(cache: SnapshotCache):
    with cache.lock("acct1", timeout_seconds=1):
        assert (cache.dir / "acct1.lock").exists()
    assert not (cache.dir / "acct1.lock").exists()


def test_lock_times_out_when_held(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    (cache.dir / "acct1.lock").write_text(str(int(time.time())))
    with pytest.raises(TimeoutError):
        with cache.lock("acct1", timeout_seconds=0.1):
            pass


def test_stale_lock_is_reclaimed(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    # Lock written with timestamp from 60 seconds ago — past stale threshold.
    (cache.dir / "acct1.lock").write_text(str(int(time.time()) - 60))
    with cache.lock("acct1", timeout_seconds=0.1, stale_seconds=30):
        pass  # should succeed


def test_prune_removes_old_snapshots(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    old = cache.dir / "old.json"
    old.write_text("{}")
    import os
    long_ago = time.time() - 86400 * 31
    os.utime(old, (long_ago, long_ago))
    cache.prune(max_age_days=30)
    assert not old.exists()


def test_prune_keeps_index_and_audit(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    keep_index = cache.dir / ".index.json"
    keep_audit = cache.dir / "audit.log"
    keep_index.write_text("{}")
    keep_audit.write_text("")
    import os
    long_ago = time.time() - 86400 * 31
    os.utime(keep_index, (long_ago, long_ago))
    os.utime(keep_audit, (long_ago, long_ago))
    cache.prune(max_age_days=30)
    assert keep_index.exists()
    assert keep_audit.exists()
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_cache.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`agent/src/integrations/indmoney/cache.py`:

```python
"""Snapshot cache + index + per-account concurrent-fetch lock.

Cache files live under ``<root>/indmoney/``. The index is a JSON dict at
``.index.json`` mapping ``"<account>:<kind>:<key>"`` → ``{path, asof, expires_at}``.
A corrupt index is silently rebuilt as empty (the raw snapshot files on disk
remain authoritative for analytics — the index is just a freshness shortcut).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

CACHE_DIR_NAME = "indmoney"
INDEX_FILE = ".index.json"
AUDIT_FILE = "audit.log"

_PROTECTED_FILES = {INDEX_FILE, AUDIT_FILE}


class SnapshotCache:
    """TTL-gated snapshot cache for INDMoney responses."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / CACHE_DIR_NAME
        self._index: dict[str, dict[str, Any]] = {}
        self._index_loaded = False

    # ---- index ---------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> None:
        self._ensure_dir()
        path = self.dir / INDEX_FILE
        if not path.exists():
            self._index = {}
            self._index_loaded = True
            return
        try:
            self._index = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(self._index, dict):
                raise ValueError("index is not a dict")
        except Exception as exc:
            logger.warning("indmoney: index corrupt (%s) — rebuilding empty", exc)
            self._index = {}
        self._index_loaded = True

    def _save_index(self) -> None:
        self._ensure_dir()
        path = self.dir / INDEX_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._index, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    # ---- get / put -----------------------------------------------------

    @staticmethod
    def _key(account: str, kind: str, key: str) -> str:
        return f"{account}:{kind}:{key}"

    def put(self, account: str, kind: str, key: str, value: dict[str, Any],
            ttl_seconds: int) -> Path:
        """Persist a snapshot and update the index. Returns the file path."""
        if not self._index_loaded:
            self._load_index()
        self._ensure_dir()
        asof = int(time.time())
        filename = f"{account}_{kind}_{asof}.json"
        path = self.dir / filename
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        self._index[self._key(account, kind, key)] = {
            "path": filename,
            "asof": asof,
            "expires_at": asof + max(0, ttl_seconds),
        }
        self._save_index()
        return path

    def get(self, account: str, kind: str, key: str, *,
            force_refresh: bool = False) -> dict[str, Any] | None:
        """Return cached snapshot dict if fresh; else None."""
        if force_refresh:
            return None
        if not self._index_loaded:
            self._load_index()
        entry = self._index.get(self._key(account, kind, key))
        if not entry:
            return None
        if entry.get("expires_at", 0) <= time.time():
            return None
        path = self.dir / entry["path"]
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("indmoney: snapshot %s unreadable (%s)", path, exc)
            return None

    # ---- lock ----------------------------------------------------------

    @contextlib.contextmanager
    def lock(self, account: str, *, timeout_seconds: float = 30.0,
             stale_seconds: float = 30.0) -> Iterator[None]:
        """Per-account fetch lock. Reclaims locks older than ``stale_seconds``."""
        self._ensure_dir()
        path = self.dir / f"{account}.lock"
        deadline = time.time() + timeout_seconds
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(int(time.time())).encode("utf-8"))
                os.close(fd)
                break
            except FileExistsError:
                # Reclaim if stale.
                try:
                    held_at = int(path.read_text(encoding="utf-8").strip() or "0")
                except Exception:
                    held_at = 0
                if time.time() - held_at > stale_seconds:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue
                if time.time() >= deadline:
                    raise TimeoutError(f"INDMoney lock for {account!r} held > {timeout_seconds}s")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    # ---- prune ---------------------------------------------------------

    def prune(self, *, max_age_days: int = 30) -> int:
        """Delete snapshot files older than ``max_age_days``. Returns count."""
        if not self.dir.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for child in self.dir.iterdir():
            if child.name in _PROTECTED_FILES:
                continue
            if child.suffix == ".lock":
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    child.unlink()
                    removed += 1
            except FileNotFoundError:
                pass
        return removed
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_cache.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations/indmoney/cache.py agent/tests/test_indmoney_cache.py
git commit -m "feat(indmoney): TTL snapshot cache, index, fetch lock"
```

---

## Task 5: Audit log

**Files:**
- Create: `agent/src/integrations/indmoney/audit.py`
- Test: `agent/tests/test_indmoney_audit.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_audit.py`:

```python
"""Tests for the append-only audit log."""

from __future__ import annotations

import re
from pathlib import Path

from src.integrations.indmoney.audit import append_audit


def test_append_writes_one_line(tmp_path: Path):
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="fetch_holdings", outcome="ok",
                 detail="42 positions")
    line = log.read_text().splitlines()
    assert len(line) == 1
    assert "acct1" in line[0]
    assert "fetch_holdings" in line[0]
    assert "42 positions" in line[0]


def test_append_redacts_token_substrings(tmp_path: Path):
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="refresh", outcome="ok",
                 detail="Authorization: Bearer abc123-fake-token-xyz")
    body = log.read_text()
    assert "abc123" not in body
    assert "<redacted>" in body


def test_append_format_is_iso_timestamp(tmp_path: Path):
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="x", outcome="ok", detail="")
    line = log.read_text().splitlines()[0]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_audit.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`agent/src/integrations/indmoney/audit.py`:

```python
"""Append-only INDMoney audit log.

One line per successful or failed MCP call. No PII. No tokens. Bearer
substrings are redacted defensively even if a caller forgets.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def _redact(text: str) -> str:
    return _BEARER_RE.sub("Bearer <redacted>", text)


def append_audit(path: Path, *, account: str, action: str, outcome: str,
                 detail: str = "") -> None:
    """Append one line to the audit log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    line = f"{ts}\t{account}\t{action}\t{outcome}\t{_redact(detail)}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_audit.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations/indmoney/audit.py agent/tests/test_indmoney_audit.py
git commit -m "feat(indmoney): append-only audit log with bearer redaction"
```

---

## Task 6: Auth — token cache + atomic refresh

> **Note:** The OAuth flow itself (browser-launching) is delegated to
> `oauth-cli-kit` in Task 11 (CLI subcommand). This task implements only the
> *storage* and *refresh* primitives the client needs at request time.

**Files:**
- Create: `agent/src/integrations/indmoney/auth.py`
- Test: `agent/tests/test_indmoney_auth.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_auth.py`:

```python
"""Tests for INDMoney TokenCache (load / save / refresh)."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import httpx
import pytest

from src.integrations.indmoney.auth import (
    StaleTokenError,
    Token,
    TokenCache,
)


def _fresh_token(**kw) -> Token:
    base = dict(
        access_token="acc_1",
        refresh_token="ref_1",
        expires_at=int(time.time()) + 3600,
        account_id="acct1",
        issued_at=int(time.time()),
    )
    base.update(kw)
    return Token(**base)


def test_save_creates_file_with_0600_mode(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token())
    mode = stat.S_IMODE(os.stat(cache.path).st_mode)
    assert mode == 0o600


def test_save_uses_atomic_rename(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token(access_token="v1"))
    # Force partial write failure: replace with a directory at the temp path.
    tmp = cache.path.with_suffix(".json.tmp")
    if tmp.exists():
        tmp.unlink()
    cache.save(_fresh_token(access_token="v2"))
    loaded = cache.load()
    assert loaded is not None
    assert loaded.access_token == "v2"


def test_load_returns_none_when_missing(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "missing.json")
    assert cache.load() is None


def test_refresh_failure_preserves_existing_token(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token(access_token="original", refresh_token="r1"))

    def failing(refresh_token: str) -> dict:
        raise httpx.HTTPStatusError("400", request=None, response=None)  # type: ignore[arg-type]

    with pytest.raises(StaleTokenError):
        cache.refresh(token_endpoint="https://example/token", http_post=failing)

    # File still has original.
    raw = json.loads(cache.path.read_text())
    assert raw["access_token"] == "original"


def test_refresh_success_updates_file(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token(access_token="old", refresh_token="r1"))

    def ok(refresh_token: str) -> dict:
        assert refresh_token == "r1"
        return {"access_token": "new", "refresh_token": "r2", "expires_in": 7200}

    new = cache.refresh(token_endpoint="https://example/token", http_post=ok)
    assert new.access_token == "new"
    assert new.refresh_token == "r2"
    on_disk = json.loads(cache.path.read_text())
    assert on_disk["access_token"] == "new"


def test_token_is_expired():
    t = _fresh_token(expires_at=int(time.time()) - 1)
    assert t.is_expired()
    fresh = _fresh_token()
    assert not fresh.is_expired()
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_auth.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`agent/src/integrations/indmoney/auth.py`:

```python
"""OAuth token storage + refresh for INDMoney.

The actual OAuth code → token exchange (browser launch, PKCE, etc.) is owned
by the CLI subcommand (``vibe-trading indmoney login``) which delegates to
``oauth-cli-kit``. This module is responsible only for:

  * Reading and writing the token file with mode 0o600
  * Atomic writes (temp file + rename) so a partial write never corrupts
    a previously-good token
  * Refreshing an expired access_token via the refresh_token, while
    leaving the on-disk token UNTOUCHED if the refresh fails
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_TOKEN_PATH = Path("~/.vibe-trading/indmoney/token.json").expanduser()


class StaleTokenError(RuntimeError):
    """Raised when a refresh attempt fails. The on-disk token is untouched."""


@dataclass(frozen=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: int  # epoch seconds
    account_id: str
    issued_at: int

    def is_expired(self, *, skew_seconds: int = 30) -> bool:
        return time.time() + skew_seconds >= self.expires_at


HttpPost = Callable[[str], dict[str, Any]]
"""Callable taking the refresh_token and returning a JSON token-endpoint response."""


class TokenCache:
    """File-backed token store with atomic write and refresh."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_TOKEN_PATH

    # ---- load / save ---------------------------------------------------

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return Token(**data)
        except TypeError:
            return None

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(token), indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ---- refresh -------------------------------------------------------

    def refresh(
        self,
        *,
        token_endpoint: str,
        http_post: HttpPost,
    ) -> Token:
        """Exchange refresh_token for a new access_token.

        Args:
            token_endpoint: URL — passed through to ``http_post`` for logging.
            http_post: Callable that performs the POST and returns the JSON.
                Injected so tests can stub the network without mocking httpx.

        Raises:
            StaleTokenError: refresh failed; on-disk token is untouched.
        """
        current = self.load()
        if current is None:
            raise StaleTokenError("no token to refresh")
        try:
            payload = http_post(current.refresh_token)
        except Exception as exc:
            raise StaleTokenError(f"refresh failed: {exc}") from exc

        access = payload.get("access_token")
        if not access:
            raise StaleTokenError("refresh response missing access_token")
        new = Token(
            access_token=access,
            refresh_token=payload.get("refresh_token") or current.refresh_token,
            expires_at=int(time.time()) + int(payload.get("expires_in", 3600)),
            account_id=current.account_id,
            issued_at=int(time.time()),
        )
        self.save(new)
        return new
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_auth.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations/indmoney/auth.py agent/tests/test_indmoney_auth.py
git commit -m "feat(indmoney): TokenCache with atomic write and refresh"
```

---

## Task 7: MCP client wrapper

> **Note:** MCP transport over HTTP is JSON-RPC 2.0. This wrapper uses
> ``httpx`` directly (already a dep) for full control over auth headers,
> retries, and rate-limit observation. After Task 0 confirms whether
> ``mcp.indmoney.com/mcp`` requires SSE or supports plain HTTP request /
> response, the engineer may swap to ``fastmcp.Client`` if SSE is required —
> the public method signatures here stay the same.

**Files:**
- Create: `agent/src/integrations/indmoney/client.py`
- Test: `agent/tests/test_indmoney_client.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_client.py`:

```python
"""Tests for IndMoneyClient (MCP wrapper) using a stub transport."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache
from src.integrations.indmoney.client import IndMoneyClient


def _seed_token(tmp_path: Path) -> TokenCache:
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(Token(
        access_token="acc_ok", refresh_token="ref_ok",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))
    return cache


def _make_client(tmp_path: Path, handler) -> IndMoneyClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://mcp.indmoney.com")
    return IndMoneyClient(
        url="https://mcp.indmoney.com/mcp",
        token_cache=_seed_token(tmp_path),
        http=http,
        token_endpoint="https://mcp.indmoney.com/oauth/token",
    )


def test_call_tool_happy_path(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "get_holdings"
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": {"positions": []}}]},
        })

    client = _make_client(tmp_path, handler)
    result = client.call_tool("get_holdings", {})
    assert result == {"positions": []}


def test_call_tool_401_then_refresh_then_retry(tmp_path: Path):
    state = {"calls": 0, "refresh_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            state["refresh_calls"] += 1
            return httpx.Response(200, json={"access_token": "acc_new", "refresh_token": "ref_new", "expires_in": 3600})
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": {"ok": True}}]},
        })

    client = _make_client(tmp_path, handler)
    result = client.call_tool("get_holdings", {})
    assert result == {"ok": True}
    assert state["refresh_calls"] == 1
    assert state["calls"] == 2  # original 401 + retry


def test_call_tool_401_then_refresh_fails_raises(tmp_path: Path):
    from src.integrations.indmoney.auth import StaleTokenError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(401)

    client = _make_client(tmp_path, handler)
    with pytest.raises(StaleTokenError):
        client.call_tool("get_holdings", {})


def test_call_tool_429_honours_retry_after(tmp_path: Path):
    from src.integrations.indmoney.client import RateLimitedError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "13"}, json={"error": "throttled"})

    client = _make_client(tmp_path, handler)
    with pytest.raises(RateLimitedError) as exc_info:
        client.call_tool("get_holdings", {})
    assert exc_info.value.retry_after_seconds == 13


def test_call_tool_5xx_retries_once_then_upstream_error(tmp_path: Path):
    from src.integrations.indmoney.client import UpstreamError

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(503, json={"error": "down"})

    client = _make_client(tmp_path, handler)
    with pytest.raises(UpstreamError):
        client.call_tool("get_holdings", {})
    assert state["calls"] == 2  # original + 1 retry
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`agent/src/integrations/indmoney/client.py`:

```python
"""INDMoney MCP HTTP client.

Speaks JSON-RPC 2.0 over HTTPS to ``mcp.indmoney.com/mcp``. Handles:
  - Authorization: Bearer <access_token>
  - 401 → refresh token → retry once
  - 429 → raise RateLimitedError with Retry-After
  - 5xx → one retry with 2s backoff, then UpstreamError
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
        http: ``httpx.Client`` (injectable for tests).
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

    # ---- public --------------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tools/call`` and return the unwrapped JSON result."""
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    # ---- internals -----------------------------------------------------

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(self._ids),
                   "method": method, "params": params}
        # First try.
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
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations/indmoney/client.py agent/tests/test_indmoney_client.py
git commit -m "feat(indmoney): MCP HTTP client with auth refresh and retries"
```

---

## Task 8: Holdings tool

**Files:**
- Create: `agent/src/tools/indmoney_holdings_tool.py`
- Test: covered by `agent/tests/test_indmoney_tool_contract.py` (Task 10)

> Tool registration is automatic via `agent/src/tools/__init__.py::_discover_subclasses()`. Just dropping the file in this directory wires it into both the agent ReAct loop and `vibe-trading-mcp`.

- [ ] **Step 1: Write the implementation**

`agent/src/tools/indmoney_holdings_tool.py`:

```python
"""IndMoney holdings tool — read current positions + cash."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.integrations.indmoney import ErrorKind, build_error
from src.integrations.indmoney.audit import append_audit
from src.integrations.indmoney.auth import StaleTokenError, TokenCache
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

        import httpx  # local import — keeps cold-start light
        with httpx.Client(timeout=30.0) as http:
            client = IndMoneyClient(
                url=DEFAULT_URL, token_cache=tokens, http=http,
                token_endpoint=DEFAULT_TOKEN_URL,
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
        append_audit(cache.dir / "audit.log",
                     account=token.account_id, action="fetch_holdings",
                     outcome="ok",
                     detail=f"{len(holdings)} positions")
        return json.dumps({"ok": True, **snapshot,
                           "snapshot_path": str(snap_path),
                           "from_cache": False})
```

- [ ] **Step 2: Smoke test (pre-contract)**

```bash
python -c "from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool; t = IndMoneyHoldingsTool(); print(t.name, t.description[:50])"
```

Expected: prints `indmoney_holdings ...` with no import errors.

- [ ] **Step 3: Commit**

```bash
git add agent/src/tools/indmoney_holdings_tool.py
git commit -m "feat(indmoney): holdings tool"
```

---

## Task 9: Transactions tool

**Files:**
- Create: `agent/src/tools/indmoney_transactions_tool.py`

- [ ] **Step 1: Write the implementation**

`agent/src/tools/indmoney_transactions_tool.py`:

```python
"""IndMoney transactions tool — date-range history → TradeRecord CSV + events CSV."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.integrations.indmoney import ErrorKind, build_error
from src.integrations.indmoney.audit import append_audit
from src.integrations.indmoney.auth import StaleTokenError, TokenCache
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

        import httpx
        with httpx.Client(timeout=30.0) as http:
            client = IndMoneyClient(
                url=DEFAULT_URL, token_cache=tokens, http=http,
                token_endpoint=DEFAULT_TOKEN_URL,
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
```

- [ ] **Step 2: Smoke test**

```bash
python -c "from src.tools.indmoney_transactions_tool import IndMoneyTransactionsTool; t = IndMoneyTransactionsTool(); print(t.name)"
```

Expected: prints `indmoney_transactions`.

- [ ] **Step 3: Commit**

```bash
git add agent/src/tools/indmoney_transactions_tool.py
git commit -m "feat(indmoney): transactions tool with trades+events CSV"
```

---

## Task 10: Sync tool + tool-contract end-to-end tests

**Files:**
- Create: `agent/src/tools/indmoney_sync_tool.py`
- Test: `agent/tests/test_indmoney_tool_contract.py`

- [ ] **Step 1: Write the failing test**

`agent/tests/test_indmoney_tool_contract.py`:

```python
"""End-to-end contract tests for the three INDMoney tools.

Uses httpx.MockTransport to simulate the MCP server. Verifies the JSON
envelope shape from each tool under happy and error paths.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect uploads root + token path to a tmp dir."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "token.json",
    )
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(Token(
        access_token="acc", refresh_token="ref",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))


def _stub_transport(responses: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = body.get("params", {}).get("name", "")
        payload = responses.get(name, {})
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "json", "json": payload}]},
        })
    return httpx.MockTransport(handler)


def test_holdings_tool_happy_path(monkeypatch, tmp_path):
    transport = _stub_transport({
        "get_holdings": {"asof": "2026-05-07T14:30:00+05:30",
                          "positions": [{"symbol": "AAPL", "name": "Apple",
                                         "quantity": 1, "avg_cost": 1, "market_value": 2,
                                         "unrealized_pnl": 1, "currency": "USD",
                                         "instrument_type": "equity"}]},
        "get_account": {"asof": "2026-05-07T14:30:00+05:30",
                         "cash_usd": 100.0, "cash_inr": 0, "pending_settlement_usd": 0},
    })
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **kw: httpx.Client(transport=transport))
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = json.loads(IndMoneyHoldingsTool().execute(force_refresh=True))
    assert out["ok"] is True
    assert out["holdings"][0]["symbol"] == "AAPL"
    assert out["cash"]["cash_usd"] == 100.0
    assert "snapshot_path" in out


def test_holdings_tool_needs_auth_when_no_token(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "absent.json",
    )
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = json.loads(IndMoneyHoldingsTool().execute())
    assert out["ok"] is False
    assert out["error_kind"] == "needs_auth"


def test_transactions_tool_writes_both_csvs(monkeypatch, tmp_path):
    transport = _stub_transport({
        "get_transactions": {
            "items": [
                {"datetime": "2026-04-01", "symbol": "AAPL", "name": "Apple",
                 "type": "buy", "quantity": 1, "price": 150.0, "amount": 150.0,
                 "fee": 0.0, "currency": "USD"},
                {"datetime": "2026-04-02", "symbol": "AAPL", "name": "Apple",
                 "type": "dividend", "quantity": 0, "price": 0.0, "amount": 0.5,
                 "fee": 0.0, "currency": "USD"},
            ]
        }
    })
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **kw: httpx.Client(transport=transport))
    from src.tools.indmoney_transactions_tool import IndMoneyTransactionsTool
    out = json.loads(IndMoneyTransactionsTool().execute(
        start_date="2026-04-01", end_date="2026-04-30", force_refresh=True))
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["events_count"] == 1
    assert Path(out["csv_path"]).exists()
    assert Path(out["events_csv_path"]).exists()


def test_sync_tool_returns_aggregate_status(monkeypatch, tmp_path):
    transport = _stub_transport({
        "get_holdings":     {"asof": "2026-05-07", "positions": []},
        "get_account":      {"asof": "2026-05-07", "cash_usd": 0, "cash_inr": 0, "pending_settlement_usd": 0},
        "get_transactions": {"items": []},
    })
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **kw: httpx.Client(transport=transport))
    from src.tools.indmoney_sync_tool import IndMoneySyncTool
    out = json.loads(IndMoneySyncTool().execute())
    assert out["ok"] is True
    assert out["status"] == "ok"
    assert out["holdings_count"] == 0
    assert out["transactions_count"] == 0


def test_sync_tool_needs_auth_returns_auth_url(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "absent.json",
    )
    from src.tools.indmoney_sync_tool import IndMoneySyncTool
    out = json.loads(IndMoneySyncTool().execute())
    assert out["ok"] is False
    assert out["error_kind"] == "needs_auth"
    # auth_url is None for v1 (the CLI subcommand drives the OAuth flow);
    # field is present so future plumbing doesn't change the schema.
    assert "auth_url" in out
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest agent/tests/test_indmoney_tool_contract.py -v
```

Expected: ImportError on `IndMoneySyncTool`.

- [ ] **Step 3: Implement the sync tool**

`agent/src/tools/indmoney_sync_tool.py`:

```python
"""IndMoney sync tool — refresh holdings + cash + recent transactions in one call."""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
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
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_tool_contract.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/src/tools/indmoney_sync_tool.py agent/tests/test_indmoney_tool_contract.py
git commit -m "feat(indmoney): sync tool + end-to-end contract tests"
```

---

## Task 11: CLI — `indmoney login` and `indmoney status`

**Files:**
- Modify: `agent/cli.py` (add subparser around line 1776, command handler near `cmd_provider_login` at line 1721)

- [ ] **Step 1: Add the command handlers near the existing OAuth provider handler**

Locate `cmd_provider_login` at `agent/cli.py:1721` and add directly after it:

```python
def cmd_indmoney_login() -> int:
    """Run interactive OAuth for INDMoney via oauth-cli-kit."""
    try:
        from oauth_cli_kit import login_oauth_interactive
    except ImportError:
        console.print("[red]oauth-cli-kit is not installed.[/red] Run: pip install oauth-cli-kit")
        return EXIT_USAGE_ERROR
    try:
        console.print("[cyan]Starting INDMoney OAuth login...[/cyan]\n")
        # Provider config (issuer, client_id, scopes, authorization_endpoint,
        # token_endpoint) comes from the discovery notes you captured in Task 0
        # at docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md.
        #
        # Path A (preferred if oauth-cli-kit supports it): pass the metadata
        # directly to login_oauth_interactive. Inspect the library's API:
        #   python -c "from oauth_cli_kit import login_oauth_interactive; help(login_oauth_interactive)"
        #
        # Path B (fallback): if the library has no provider hook, implement
        # Authorization Code + PKCE (RFC 6749 §4.1 + RFC 7636) directly with
        # httpx. The shape is roughly:
        #   1. Generate code_verifier (random URL-safe 64 chars) and
        #      code_challenge = base64url(sha256(verifier)) without padding.
        #   2. Open authorization_endpoint?response_type=code&client_id=...
        #      &redirect_uri=http://127.0.0.1:<port>/callback&code_challenge=...
        #      &code_challenge_method=S256&scope=<from discovery>
        #   3. Run an http.server on 127.0.0.1:<port> to receive ?code=...
        #   4. POST to token_endpoint with grant_type=authorization_code,
        #      code, redirect_uri, client_id, code_verifier.
        #   5. Persist the response into TokenCache (see below).
        # Keep this in agent/src/integrations/indmoney/auth.py as
        # ``run_authorization_code_pkce(metadata, client_id, scopes)`` and
        # call it from here; do NOT inline the flow into cli.py.
        token = login_oauth_interactive(
            provider="indmoney",
            print_fn=lambda text: console.print(text),
            prompt_fn=lambda text: Prompt.ask(text),
        )
        if not token or not getattr(token, "access", None):
            console.print("[red]Authentication did not return a token.[/red]")
            return EXIT_RUN_FAILED

        # Persist via our TokenCache so the tools can read it.
        from src.integrations.indmoney.auth import Token, TokenCache
        import time as _time
        TokenCache().save(Token(
            access_token=token.access,
            refresh_token=getattr(token, "refresh", "") or "",
            expires_at=int(_time.time()) + int(getattr(token, "expires_in", 3600) or 3600),
            account_id=getattr(token, "account_id", "") or "default",
            issued_at=int(_time.time()),
        ))
        console.print(f"[green]Authenticated with INDMoney[/green]  [dim]{getattr(token, 'account_id', 'default')}[/dim]")
        return EXIT_SUCCESS
    except Exception as exc:
        console.print(f"[red]Authentication error:[/red] {exc}")
        return EXIT_RUN_FAILED


def cmd_indmoney_status() -> int:
    """Print whether an INDMoney token is present and not expired."""
    from src.integrations.indmoney.auth import TokenCache
    token = TokenCache().load()
    if token is None:
        console.print("[yellow]No INDMoney token. Run: vibe-trading indmoney login[/yellow]")
        return EXIT_USAGE_ERROR
    expired = token.is_expired()
    state = "[red]expired[/red]" if expired else "[green]valid[/green]"
    console.print(f"INDMoney: {state}  account={token.account_id}  expires_at={token.expires_at}")
    return EXIT_SUCCESS
```

- [ ] **Step 2: Wire the subparser**

In `_build_parser()` around line 1776 (after `subparsers = parser.add_subparsers(...)`), add:

```python
    indmoney_parser = subparsers.add_parser("indmoney", help="Manage INDMoney integration")
    indmoney_subparsers = indmoney_parser.add_subparsers(dest="indmoney_command")
    indmoney_subparsers.add_parser("login", help="Authenticate with INDMoney via OAuth")
    indmoney_subparsers.add_parser("status", help="Show INDMoney token status")
```

- [ ] **Step 3: Wire the dispatcher**

Find the block that dispatches by `args.command` (the same block that handles `args.command == "provider"`) and add a parallel branch:

```python
    elif args.command == "indmoney":
        sub = getattr(args, "indmoney_command", None)
        if sub == "login":
            return cmd_indmoney_login()
        if sub == "status":
            return cmd_indmoney_status()
        console.print("[red]indmoney requires a subcommand.[/red] Try: vibe-trading indmoney login")
        return EXIT_USAGE_ERROR
```

- [ ] **Step 4: Smoke test**

```bash
vibe-trading indmoney status
```

Expected (no token yet): `[yellow]No INDMoney token. Run: vibe-trading indmoney login[/yellow]`, exit code = `EXIT_USAGE_ERROR` (2).

- [ ] **Step 5: Commit**

```bash
git add agent/cli.py
git commit -m "feat(indmoney): CLI subcommands login and status"
```

---

## Task 12: Security tests — path safety, secret leakage, remote gate

**Files:**
- Create: `agent/tests/test_indmoney_path_safety.py`
- Create: `agent/tests/test_indmoney_secret_leakage.py`
- Create: `agent/tests/test_indmoney_remote_gate.py`

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_indmoney_path_safety.py`:

```python
"""Path-safety tests for the INDMoney cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.integrations.indmoney.cache import SnapshotCache


def test_account_id_with_traversal_does_not_escape_cache_dir(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    bad = "../../../etc/passwd"
    cache.put(bad, "holdings", "k", {"x": 1}, ttl_seconds=60)
    # No file may exist outside cache.dir.
    for child in tmp_path.rglob("*"):
        if child.is_file():
            assert tmp_path in child.resolve().parents or child.resolve().parent == tmp_path
            assert cache.dir in child.resolve().parents or child.resolve().parent == cache.dir


def test_lock_file_with_traversal_does_not_escape(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    cache.dir.mkdir(parents=True, exist_ok=True)
    bad = "../../boom"
    with pytest.raises((TimeoutError, OSError, ValueError)):
        # We expect either rejection, or successful lock under cache.dir
        # — but never a file at tmp_path/boom.
        with cache.lock(bad, timeout_seconds=0.1):
            pass
    assert not (tmp_path / "boom.lock").exists()
    assert not (tmp_path.parent / "boom.lock").exists()
```

> **Implementation note (Task 12):** if the path-traversal tests fail, harden
> `cache.put` and `cache.lock` to enforce that the resolved file path is
> ``Path.is_relative_to(self.dir)``. Either reject (raise `ValueError`) or
> sanitize by replacing path separators in the account_id with `_`. Pick
> reject; sanitization can mask bugs.

`agent/tests/test_indmoney_secret_leakage.py`:

```python
"""Verify tokens never leak into tool output, audit logs, or tracebacks."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from src.integrations.indmoney.auth import Token, TokenCache


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "token.json",
    )
    TokenCache(path=tmp_path / "token.json").save(Token(
        access_token="SECRET-DO-NOT-LEAK",
        refresh_token="REFRESH-DO-NOT-LEAK",
        expires_at=int(time.time()) + 3600,
        account_id="acct1", issued_at=int(time.time()),
    ))


def test_holdings_tool_output_excludes_token(monkeypatch):
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "json", "json": {"asof": "x", "positions": []}}]},
    }))
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **kw: httpx.Client(transport=transport))
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = IndMoneyHoldingsTool().execute(force_refresh=True)
    assert "SECRET-DO-NOT-LEAK" not in out
    assert "REFRESH-DO-NOT-LEAK" not in out


def test_audit_log_redacts_tokens(tmp_path):
    from src.integrations.indmoney.audit import append_audit
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="x", outcome="err",
                 detail="GET / 401 — Authorization: Bearer SECRET-DO-NOT-LEAK")
    assert "SECRET-DO-NOT-LEAK" not in log.read_text()


def test_tool_error_envelope_does_not_include_token(monkeypatch):
    # Make MCP return 401 + force refresh failure.
    def handler(req: httpx.Request) -> httpx.Response:
        if "/oauth/token" in str(req.url):
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(401)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **kw: httpx.Client(transport=transport))
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    out = IndMoneyHoldingsTool().execute(force_refresh=True)
    assert "SECRET-DO-NOT-LEAK" not in out
    body = json.loads(out)
    assert body["ok"] is False
    assert body["error_kind"] == "stale_token"
```

`agent/tests/test_indmoney_remote_gate.py`:

```python
"""Verify the VIBE_TRADING_ENABLE_INDMONEY gate for non-loopback callers."""

from __future__ import annotations

import json

import pytest


def _exec_holdings():
    from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
    return json.loads(IndMoneyHoldingsTool().execute())


def test_remote_caller_without_gate_is_blocked(monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_REMOTE_CALL", "1")
    monkeypatch.delenv("VIBE_TRADING_ENABLE_INDMONEY", raising=False)
    out = _exec_holdings()
    assert out["ok"] is False
    assert out["error_kind"] == "config_missing"


def test_remote_caller_with_gate_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_TRADING_REMOTE_CALL", "1")
    monkeypatch.setenv("VIBE_TRADING_ENABLE_INDMONEY", "1")
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "missing.json",
    )
    out = _exec_holdings()
    # Token is missing, so we should see needs_auth — NOT config_missing.
    assert out["error_kind"] == "needs_auth"


def test_local_caller_passes_without_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("VIBE_TRADING_REMOTE_CALL", raising=False)
    monkeypatch.delenv("VIBE_TRADING_ENABLE_INDMONEY", raising=False)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    monkeypatch.setattr(
        "src.integrations.indmoney.auth.DEFAULT_TOKEN_PATH",
        tmp_path / "missing.json",
    )
    out = _exec_holdings()
    assert out["error_kind"] == "needs_auth"  # local CLI: no gate, but no token
```

- [ ] **Step 2: Run — see failures, then harden as needed**

```bash
pytest agent/tests/test_indmoney_path_safety.py agent/tests/test_indmoney_secret_leakage.py agent/tests/test_indmoney_remote_gate.py -v
```

If any path-safety test fails, edit `agent/src/integrations/indmoney/cache.py` to enforce path containment in `put()` and `lock()`:

```python
# Top of cache.py — utility:
import re
_BAD_ACCT_RE = re.compile(r"[^A-Za-z0-9._-]")

def _safe_account(account: str) -> str:
    if not account or _BAD_ACCT_RE.search(account):
        raise ValueError(f"Unsafe account id: {account!r}")
    return account
```

Then call `_safe_account(account)` at the start of `put()` and `lock()` and use the validated value when building file paths. Re-run the test suite.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_indmoney_path_safety.py agent/tests/test_indmoney_secret_leakage.py agent/tests/test_indmoney_remote_gate.py agent/src/integrations/indmoney/cache.py
git commit -m "test(indmoney): security tests for paths, secrets, remote gate"
```

---

## Task 13: Registry smoke test + MCP cross-publication check

**Files:**
- Create: `agent/tests/test_indmoney_registry.py`

- [ ] **Step 1: Write the failing test**

```python
"""Verify the three INDMoney tools are auto-discovered and MCP-published."""

from __future__ import annotations


def test_three_indmoney_tools_in_local_registry():
    from src.tools import build_registry
    reg = build_registry()
    names = set(reg.tool_names)
    assert {"indmoney_holdings", "indmoney_transactions", "indmoney_sync"} <= names


def test_indmoney_tools_have_openai_schema():
    from src.tools import build_registry
    reg = build_registry()
    for name in ("indmoney_holdings", "indmoney_transactions", "indmoney_sync"):
        tool = reg.get(name)
        assert tool is not None
        schema = tool.to_openai_schema()
        assert schema["function"]["name"] == name
        assert "parameters" in schema["function"]


def test_mcp_server_enumerates_indmoney_tools():
    """mcp_server.py builds the same registry; smoke check that import works
    and the three tools surface in the underlying registry."""
    import importlib
    mcp_module = importlib.import_module("mcp_server")
    # mcp_server uses _get_registry() lazily; force build via build_registry.
    from src.tools import build_registry
    names = set(build_registry().tool_names)
    assert {"indmoney_holdings", "indmoney_transactions", "indmoney_sync"} <= names
    # mcp_module reference kept to ensure no import-time crash:
    assert hasattr(mcp_module, "_get_registry") or hasattr(mcp_module, "build_registry")
```

- [ ] **Step 2: Run — verify pass**

```bash
pytest agent/tests/test_indmoney_registry.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add agent/tests/test_indmoney_registry.py
git commit -m "test(indmoney): registry + mcp cross-publication smoke"
```

---

## Task 14: README + CI smoke

**Files:**
- Create: `agent/src/integrations/indmoney/README.md`

- [ ] **Step 1: Write the README**

````markdown
# INDMoney MCP Integration

Read-only INDMoney portfolio access: holdings, transactions, cash. Powers the
existing `trade_journal_tool` and `shadow_account_tool` analytics with no
parser changes.

## One-time setup

```bash
pip install -e ".[dev]"      # ensures oauth-cli-kit is on the path
vibe-trading indmoney login  # opens browser for OAuth
vibe-trading indmoney status # confirms token and expiry
```

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `INDMONEY_MCP_URL` | `https://mcp.indmoney.com/mcp` | Override for staging |
| `INDMONEY_TOKEN_URL` | `https://mcp.indmoney.com/oauth/token` | OAuth token endpoint |
| `INDMONEY_TOKEN_PATH` | `~/.vibe-trading/indmoney/token.json` | Token store |
| `INDMONEY_HOLDINGS_TTL_SECONDS` | `900` | Holdings cache TTL (15 min) |
| `INDMONEY_TXNS_TTL_SECONDS` | `86400` | Transactions cache TTL (24 h) |
| `VIBE_TRADING_ENABLE_INDMONEY` | unset | Required for non-loopback API/MCP-SSE callers |

## Tools (auto-published via the registry)

| Tool | Use it for |
|---|---|
| `indmoney_holdings` | Current positions + cash |
| `indmoney_transactions` | Date-range trade history → CSV consumable by `trade_journal` |
| `indmoney_sync` | Force-refresh holdings + last 30 days of transactions |

## Manual test recipe

```bash
# 1. Authenticate
vibe-trading indmoney login

# 2. Pull holdings
vibe-trading run -p "Use indmoney_holdings to fetch my current portfolio"

# 3. Pull last 30 days and feed to trade journal
vibe-trading run -p "Use indmoney_sync, then run trade_journal on the resulting csv_path"
```

## Output files

All cache + snapshot files land under `agent/uploads/indmoney/` (already inside
the project's default sandbox roots — no allow-list change needed):

```
agent/uploads/indmoney/
├── .index.json                              # cache freshness index
├── audit.log                                # one line per MCP call
├── <account>_holdings_<ts>.json             # holdings snapshot
├── <account>_transactions_<ts>.json         # transactions snapshot
├── <account>_<start>_<end>_txns.csv         # FIFO-eligible trades CSV
└── <account>_<start>_<end>_events.csv       # dividends + splits + unknowns
```

The events CSV is intentionally separate so the existing `trade_journal_tool`
is never confused by non-trade rows (`_normalize_side` would silently coerce
them to `"buy"`).
````

- [ ] **Step 2: Run the full test suite to confirm everything is green**

```bash
pytest --ignore=agent/tests/e2e_backtest --tb=short -q -k indmoney
echo "---"
pytest --ignore=agent/tests/e2e_backtest --tb=short -q
```

Expected: all INDMoney tests pass; the full suite remains green (no regressions in existing tools, registry, or path-safety tests).

- [ ] **Step 3: Lint check**

```bash
ruff check agent/src/integrations agent/src/tools/indmoney_holdings_tool.py agent/src/tools/indmoney_transactions_tool.py agent/src/tools/indmoney_sync_tool.py agent/tests/test_indmoney_*.py
```

Expected: no errors.

- [ ] **Step 4: Frontend / CI parity check**

CI also runs `npm ci && npm run build` in `frontend/`. This task touches no frontend code — confirm by inspecting `git diff main..HEAD --stat -- frontend/`. Expected: empty.

- [ ] **Step 5: Commit**

```bash
git add agent/src/integrations/indmoney/README.md
git commit -m "docs(indmoney): integration README"
```

---

## Done definition

- [ ] All Task-1-to-14 commits land green
- [ ] `pytest --ignore=agent/tests/e2e_backtest --tb=short -q` passes (no regressions)
- [ ] `pytest --ignore=agent/tests/e2e_backtest -q -k indmoney` reports the expected count of new tests
- [ ] `ruff check agent` passes
- [ ] `vibe-trading indmoney status` works end-to-end against a live token (one human-driven smoke test)
- [ ] Section 11 of the spec has been updated with the discovery findings from Task 0 (no remaining "TBD")

When all boxes are checked, push the branch and open a PR titled `feat: INDMoney MCP integration (read-only)` referencing the spec at `docs/superpowers/specs/2026-05-07-indmoney-integration-design.md`.
