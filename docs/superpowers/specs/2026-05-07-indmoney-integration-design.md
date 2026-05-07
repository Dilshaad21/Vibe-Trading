# INDMoney MCP Integration — Design

**Status:** Draft
**Date:** 2026-05-07
**Author:** dmuthalif (with Claude Code, brainstorming skill)

## 1. Problem & goal

Bring the user's real INDMoney US-stocks portfolio into Vibe-Trading's analytics
pipeline. Today, Vibe-Trading parses Chinese broker exports (Tonghuashun,
Eastmoney, Futu) and a generic CSV format via
`agent/src/tools/trade_journal_parsers.py`, but has no path for INDMoney data.

INDMoney exposes an MCP server at `https://mcp.indmoney.com/mcp`. The goal is to
make Vibe-Trading an MCP **client** of that endpoint so holdings, transactions,
and cash flow into the existing trade-journal analytics, FIFO PnL pairing,
behavior analysis, and shadow-account reports without users hand-exporting
files.

**Out of scope for v1:** order placement / cancellation, live streaming
positions, Indian-equity backtest engines, multi-account fan-out, and a
generalized `PortfolioSource` Protocol. Each gets its own follow-up spec when
warranted.

## 2. Approach

A thin MCP-client integration module under `agent/src/integrations/indmoney/`
plus three new agent tools registered with the existing tool registry. The
registry already cross-publishes to `vibe-trading-mcp` (`agent/mcp_server.py`),
so the tools surface in both the ReAct loop and external MCP hosts with no
extra wiring.

Snapshot files (the on-disk handoff to the existing analytics) land in
`agent/uploads/indmoney/`, which is already inside the default sandbox roots
in `agent/src/tools/path_utils.py` — no path-policy changes needed.

Two alternatives were considered and rejected:

- **Generalized portfolio-source registry (Protocol + fallback chain).**
  Mirrors `backtest/loaders/registry.py`. Rejected as YAGNI: a second broker
  would justify the abstraction, but designing it blind for one consumer adds
  surface area without payoff. Easier to refactor *into* this shape later.
- **Standalone CLI that writes a snapshot, agent reads files only.** Simpler
  safety model but always slightly stale and loses the "ask now, get fresh"
  feel. We adopt its on-disk snapshot format as the cache contract while
  keeping the live MCP path.

## 3. Architecture & module layout

```
agent/src/integrations/
└── indmoney/
    ├── __init__.py
    ├── client.py        # async fastmcp.Client wrapper, retries, backoff
    ├── auth.py          # OAuth token cache + refresh (or static-key path)
    ├── normalizer.py    # INDMoney JSON → TradeRecord + Holding + CashSnapshot
    ├── cache.py         # JSON snapshots under agent/uploads/indmoney/, TTL-gated
    └── README.md        # config + manual-test recipe

agent/src/tools/
├── indmoney_holdings_tool.py       # current positions + cash (cache-first)
├── indmoney_transactions_tool.py   # date-range history → TradeRecord CSV
└── indmoney_sync_tool.py           # force refresh + emit snapshot file
```

Dependency isolation: only `client.py` and `auth.py` import `fastmcp`/`httpx`.
`normalizer.py` is pure stdlib + pandas, so it is unit-testable without
network. The agent tools are thin wrappers — orchestration, no business logic.

## 4. Auth & secrets

INDMoney's MCP endpoint is assumed to use OAuth 2.0 (modern remote-MCP
standard). The design degrades trivially if it is a static API key (the
token-cache module collapses to a single read).

> The OAuth flow described here was **not** end-to-end tested against
> `mcp.indmoney.com/mcp` during brainstorming — see Section 11 (Open
> questions). The implementation plan must include a discovery step to
> confirm the auth shape before code lands.

**Token storage**

- Path: `~/.vibe-trading/indmoney/token.json`, mode `0600`
- Schema: `{ access_token, refresh_token, expires_at, account_id, issued_at }`
- Never logged, never echoed, never written to `agent/uploads/`

**First-run flow** (driven by `indmoney_sync` tool or
`vibe-trading indmoney login` CLI):

1. Hit INDMoney's MCP discovery endpoint → fetch OAuth metadata
2. Open browser to authorization URL (mirrors
   `agent/src/providers/openai_codex.py`)
3. Local loopback callback receives the code → exchange for tokens → write
   to disk atomically (temp file + rename)
4. Subsequent calls auto-refresh on 401 with a single retry; refresh failure
   leaves the existing token file untouched

**Env-vars** (matches the existing project pattern):

- `INDMONEY_MCP_URL` — default `https://mcp.indmoney.com/mcp`
- `INDMONEY_TOKEN_PATH` — override token location for CI / multi-account
- `VIBE_TRADING_ENABLE_INDMONEY=1` — opt-in for non-loopback API/MCP-SSE
  callers; localhost dev stays low-friction. Mirrors
  `VIBE_TRADING_ENABLE_SHELL_TOOLS`.

**Failure modes the client must handle:**

- Token missing → structured `needs_auth` error, never silent 401
- Token expired and refresh fails → `stale_token` error, token file untouched
- 429 rate-limit → exponential backoff, max 3 retries, then surface error
- 5xx upstream → 1 retry with 2s backoff, then `upstream_error`

## 5. Data model & normalization

INDMoney's JSON shapes are normalized at the boundary so downstream code never
sees broker-specifics.

```python
@dataclass(frozen=True)
class Holding:
    symbol: str          # "AAPL" — exchange-qualified if non-US
    name: str
    quantity: float
    avg_cost: float      # native currency
    market_value: float  # at fetch time
    unrealized_pnl: float
    currency: str        # "USD" / "INR"
    asset_class: str     # "us_equity" / "us_etf" / "indian_equity" / "mf"
    asof: str            # ISO8601

@dataclass(frozen=True)
class CashSnapshot:
    cash_usd: float
    cash_inr: float
    pending_settlement_usd: float  # T+2 unsettled
    asof: str
```

`TradeRecord` (from `agent/src/tools/trade_journal_parsers.py`) is reused
verbatim — `(datetime, symbol, name, side, quantity, price, amount, fee,
market)` — so `trade_journal_tool` consumes our output unmodified.

**Symbol & market mapping**

- US tickers stay bare (`AAPL`, `NVDA`) → `market="us"`
- ETFs share the `us` market bucket; `asset_class="us_etf"` on `Holding`
  carries the distinction
- INR mutual funds (if exposed) → `market="other"`, `asset_class="mf"`;
  US-only analytics filter on `market`

**FX**

`currency` is preserved on `Holding` and `CashSnapshot` and never silently
converted. For v1, transactions store `price` in native currency and put
`fx_usd_inr=...` in `notes`. Extending `TradeRecord` with explicit
`fx_rate` / `fx_ccy_pair` fields is deferred — touching that dataclass
ripples through every existing parser and its tests.

**Snapshot file format** (cache + analytics handoff):

```
agent/uploads/indmoney/<account_id>_<asof_yyyymmdd_hhmm>.json
{
  "asof": "2026-05-07T14:30:00+05:30",
  "account_id": "INDM-...",
  "holdings": [Holding...],
  "cash": CashSnapshot,
  "transactions_csv": "indmoney/<account>_<asof>_txns.csv",
  "events_csv":       "indmoney/<account>_<asof>_events.csv"
}
```

The transactions CSV uses the `parse_generic` column shape (`datetime, symbol,
name, side, quantity, price, amount, fee, market`), where `side` is **only**
`"buy"` or `"sell"`. This matches `_normalize_side`'s contract in
`trade_journal_parsers.py`, which coerces any other value to `"buy"` —
mixing dividends or corporate actions into this file would silently corrupt
FIFO pairing. So:

- The transactions CSV contains only true trades.
- A sibling **events CSV** (`<account>_<asof>_events.csv`) carries dividends,
  splits, and other corporate actions in a richer schema (`datetime, symbol,
  event_type, quantity_delta, cash_delta, ratio, currency, notes`). It is
  consumed only by the shadow-account total-return calculator (a follow-on
  change behind a feature flag — see Section 11), and is ignored by the
  existing `trade_journal_tool` / FIFO pipeline.
- Both CSVs are referenced from the snapshot JSON above; either may be empty
  for a given fetch.

**Edge cases the normalizer handles:**

- Splits / corporate actions: emitted to the events CSV only, never to the
  trades CSV. FIFO PnL pairing is therefore unaffected.
- Dividends: emitted to the events CSV only, with `cash_delta` populated.
- Fractional shares: covered by `quantity: float` in the existing schema.
- Unknown transaction types: logged with WARNING and emitted to the events
  CSV with `event_type="unknown"` plus the raw payload in `notes`. Never
  silently dropped.

## 6. Tool surface

All three tools register with the existing `BaseTool` registry pattern (same
shape as `trade_journal_tool.py`). Auto-published via MCP through
`agent/mcp_server.py` with no edits there.

### `indmoney_holdings`

```
input:  { force_refresh?: bool = false }
output: { asof, account_id, holdings: [Holding...], cash, snapshot_path }
```

Cache-first (TTL 15 min). `force_refresh=true` skips the TTL check.

### `indmoney_transactions`

```
input:  { start_date: "YYYY-MM-DD", end_date: "YYYY-MM-DD",
          force_refresh?: bool = false }
output: { count, date_range, csv_path, snapshot_path }
```

Returns a `parse_generic`-format CSV path. Agent chains directly into
`trade_journal_tool(csv_path)`. TTL 24 h, keyed by
`(account_id, start_date, end_date)`.

### `indmoney_sync`

```
input:  { include_transactions_since?: "YYYY-MM-DD" = "30 days ago" }
output: { status: "ok"|"needs_auth"|"rate_limited"|"error",
          asof, holdings_count, transactions_count, snapshot_path,
          message?, auth_url? }
```

The "do everything now" entry point and auth-bootstrap path. Pairs with a
`vibe-trading indmoney login` CLI subcommand for the one-time browser OAuth.

### Error envelope (every tool)

```python
{
  "ok": false,
  "error_kind": "needs_auth" | "rate_limited" | "upstream_error"
              | "stale_token" | "config_missing",
  "message": "<human readable>",
  "retry_after_seconds": int | None,   # populated for rate_limited
  "auth_url": str | None,              # populated for needs_auth
}
```

Structured kinds let the agent decide whether to retry, ask the user, or
surface the error. Free-form strings would force the model to pattern-match.

## 7. Caching mechanics

- Cache directory: `agent/uploads/indmoney/`
- Index file: `agent/uploads/indmoney/.index.json` — keyed by
  `<account_id>:<kind>:<key>` → `{ path, asof, expires_at }`
- TTLs: `INDMONEY_HOLDINGS_TTL_SECONDS` (default 900),
  `INDMONEY_TXNS_TTL_SECONDS` (default 86400)
- Concurrent-fetch protection: `<account>.lock` sentinel file with a 30 s
  timeout prevents two parallel agent runs from racing the MCP server
- Cleanup: `indmoney_sync` prunes snapshot files older than 30 days on each
  successful run
- Recovery: a corrupt `.index.json` is rebuilt from on-disk snapshot
  filenames; the tool does not crash

## 8. Testing

**Unit tests** (no network):

- `test_indmoney_normalizer.py` — fixtures for holdings, trades,
  dividends, splits, fractional shares, INR mutual funds, and unknown
  event types. Asserts: (a) the produced `Holding` / `TradeRecord`
  shapes match what `trade_journal_tool` and the existing parsers
  consume; (b) only `side in {"buy","sell"}` rows land in the trades
  CSV; (c) dividends, splits, and unknown events land in the events
  CSV with the right `event_type` / `cash_delta` / `quantity_delta`;
  (d) feeding the trades CSV through `parse_generic` round-trips
  without `_normalize_side` collapsing anything to `"buy"`.
- `test_indmoney_cache.py` — TTL expiry, force-refresh override,
  concurrent-fetch lock, snapshot pruning, corrupt-index recovery.
- `test_indmoney_client.py` — stub `fastmcp` server. Covers happy path,
  401 → refresh → retry, refresh-fails → `needs_auth`, 429 with
  `Retry-After`, 5xx with backoff.
- `test_indmoney_auth.py` — token file mode `0600`, atomic refresh write,
  refresh failure preserves existing token.
- `test_indmoney_tool_contract.py` — end-to-end through each tool with
  the stub MCP, asserting every `error_kind` envelope shape.

**Security tests** (extends the existing `test_*_security.py` family):

- `test_indmoney_path_safety.py` — snapshot writes refuse paths outside
  `agent/uploads/indmoney/`; cache resolver is path-traversal-proof
  against a malicious `account_id`.
- `test_indmoney_secret_leakage.py` — token never appears in tool
  output, structured logs, traces, or the session-search FTS5 index.
  Failure outputs include `"<redacted>"` instead of bearer tokens.
- `test_indmoney_remote_gate.py` — without
  `VIBE_TRADING_ENABLE_INDMONEY=1`, calls from a non-loopback API
  request and from MCP-SSE return `error_kind: "config_missing"`.
  Localhost CLI / stdio MCP stay open.

## 9. Security boundaries

| Boundary | Default | Why |
|---|---|---|
| Token file location | `~/.vibe-trading/indmoney/token.json`, mode `0600` | Outside the project tree; not reachable via path-utils sandbox roots |
| Snapshot files | `agent/uploads/indmoney/` | Already inside default `VIBE_TRADING_ALLOWED_FILE_ROOTS` — analytics tools read with no policy change |
| MCP URL | `https://mcp.indmoney.com/mcp`, env-overridable | Pin in code; allow override for staging without recompile |
| Non-loopback gate | `VIBE_TRADING_ENABLE_INDMONEY=1` required | Localhost dev stays low-friction; remote API/MCP-SSE deployments must opt in |
| Read-only by design | No order tools in v1 | Section 1 commitment; revisit in a separate spec |
| Audit log | One line per successful MCP call (no PII, no token) appended to `agent/uploads/indmoney/audit.log` | Correlates portfolio anomalies with fetches |

## 10. Out of scope (v1)

- Order placement, cancellation, modification — needs its own spec with risk
  gates, dry-run mode, per-order spending caps
- Live websocket / streaming positions — TTL polling is sufficient
- Indian-equity backtest replay — China engines are A-share-specific; NSE/BSE
  needs a separate engine. Trade-journal analytics still light up regardless.
- Multi-account fan-out — single `account_id` per token; revisit if INDMoney
  exposes multiple accounts under one auth
- Generalized `PortfolioSource` Protocol — refactor when a second broker
  arrives

## 11. Open questions / things to verify in the implementation plan

1. **Auth shape.** Is `mcp.indmoney.com/mcp` OAuth 2.0, or does it use a
   static API key, or a session token? The OAuth flow in Section 4 is the
   working assumption; the implementation plan's first step must be a
   discovery call against the live endpoint to confirm.
2. **Tool surface on the INDMoney side.** Exact tool names, input schemas,
   pagination model, rate limits — all unknown until we connect. The plan
   should enumerate them before coding the normalizer fixtures.
3. **`account_id` semantics.** Is one OAuth grant tied to one INDMoney
   account, or can it span US + Indian accounts under the same login?
   Determines whether the cache key needs an account scope from day one.
4. **Currency on holdings.** Confirm whether INDMoney returns `market_value`
   in USD, INR, or both, and whether FX is provided per-line or only
   account-wide. Drives the `notes`-field FX recording in Section 5.
5. **Corporate-action representation.** The split/dividend events-CSV
   schema in Section 5 is based on common broker patterns; confirm
   against real INDMoney transaction payloads before locking the
   `event_type` enum.
6. **Shadow-account total-return calculator** is a separate follow-on
   change. v1 emits the events CSV but does not yet consume it in
   `agent/shadow_account/`. That integration ships in a follow-up spec
   once the events-CSV schema is validated against real data.
