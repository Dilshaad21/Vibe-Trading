# INDMoney MCP integration — context and reference

Canonical reference for the INDMoney portfolio integration shipped via PRs
[#1](https://github.com/Dilshaad21/Vibe-Trading/pull/1) (skeleton) and
[#2](https://github.com/Dilshaad21/Vibe-Trading/pull/2) (live-aligned reshape).
Read this before grepping the code — most of the integration's design choices
are reactions to upstream surprises that aren't visible from the file tree
alone.

If you only need user-facing setup, see the per-module
[README](../agent/src/integrations/indmoney/README.md). This doc is for
contributors who need to understand *why* the code looks the way it does.

---

## What it is

A read-only MCP **client** in Vibe-Trading that talks to INDMoney's MCP
**server** at `https://mcp.indmoney.com/mcp` (server identity `indmcp/1.27.0`)
to pull the user's full portfolio: Indian stocks, US stocks, mutual funds,
EPF/NPS retirement, FDs, gold, etc.

- **Scope:** read-only. Holdings + per-asset-type breakdowns + cash proxy.
- **Out of scope:** order placement, transaction history (INDMoney's MCP has
  no transaction stream), market-data tools (we have yfinance/AKShare for
  that already).
- **Tools exposed:** `indmoney_holdings` and `indmoney_sync` — auto-registered
  via the existing `BaseTool` registry, so they surface in both the agent
  ReAct loop and `vibe-trading-mcp` with no manual wiring.

## Quick start

```bash
# One-time OAuth dance. Opens a browser, runs Dynamic Client Registration,
# then Authorization Code + PKCE through 127.0.0.1:8765. Saves tokens and
# client credentials to ~/.vibe-trading/indmoney/{token,client}.json (mode 0600).
python scripts/indmoney_oauth.py

# Use the tools through the agent. The holdings tool calls networth_snapshot
# once for totals, then networth_holdings(asset_type=X) for each entry in
# INDMONEY_ASSET_TYPES (default IND_STOCK,US_STOCK,MF). 15-min TTL cache.
vibe-trading run -p "Use indmoney_holdings to fetch my portfolio"
```

Tokens auto-refresh on 401 (the MCP client sends `client_id` + `client_secret`
on the refresh — INDMoney is a confidential client per RFC 6749 §2.3.1).

## Architecture

```
agent/src/integrations/indmoney/
├── __init__.py        # public exports: ErrorKind, build_error, Holding, CashSnapshot
├── errors.py          # 5-kind error enum + structured envelope helper
├── types.py           # Holding, CashSnapshot dataclasses (frozen)
├── auth.py            # Token + TokenCache + ClientCredentials + refresh
├── client.py          # IndMoneyClient (JSON-RPC over HTTPS, SSE-aware)
├── normalizer.py      # MCP responses → Holding[] / cash dict / snapshot dict
├── cache.py           # TTL snapshot cache + per-account fetch lock
├── audit.py           # Append-only audit log with bearer-token redaction
└── README.md          # User-facing setup + envelope shape

agent/src/tools/
├── indmoney_holdings_tool.py   # IndMoneyHoldingsTool
└── indmoney_sync_tool.py       # IndMoneySyncTool

scripts/
├── indmoney_oauth.py     # One-shot OAuth helper (PKCE + DCR + loopback callback)
└── indmoney_discover.py  # Diagnostic probe (writes agent/tests/fixtures/indmoney/discovery.json)
```

The integration deliberately keeps `httpx`/`fastmcp` imports inside `client.py`
and `auth.py` only — `normalizer.py`, `errors.py`, `types.py`, `cache.py`,
`audit.py` are stdlib + pandas only and unit-testable without network.

`agent/uploads/indmoney/` is the on-disk snapshot directory. It already lives
inside `agent/src/tools/path_utils._default_file_roots()` so existing analytics
tools (trade journal, shadow account) can read snapshot files without
allow-list changes.

## Tool envelope (response shape)

`indmoney_holdings` and `indmoney_sync` both return JSON strings with this
shape on success:

```jsonc
{
  "ok": true,
  "asof": "",                                // INDMoney does not return one
  "account_id": "default",                   // single-account-per-token (no sub claim)
  "asset_types": ["IND_STOCK","US_STOCK","MF"],
  "totals": {
    "total_invested":      <INR>,
    "total_current_value": <INR>,
    "total_networth":      <INR>             // current - liabilities
  },
  "investments_by_asset_type": [...],        // verbatim from networth_snapshot
  "assets_by_class":          [...],
  "sector_breakdown":         [...],
  "holdings": [
    {
      "symbol":         "<INDMoney investment_code, e.g. '112192'>",
      "name":           "<full company name>",
      "quantity":       <fractional units, float>,
      "avg_cost":       <INR per unit>,      // invested_amount / total_units
      "market_value":   <INR>,
      "unrealized_pnl": <INR>,
      "currency":       "INR",               // always — see Real-world quirks
      "asset_class":    "us_equity"|"indian_equity"|"mf"|"other",
      "asof":           ""                   // not returned by INDMoney
    }
  ],
  "cash": { "cash_usd": 0.0, "cash_inr": <Liquid-class proxy>, ... },
  "snapshot_path": "<path under agent/uploads/indmoney/>",
  "from_cache":    false
}
```

On failure the structured error envelope (from `errors.py`):

```jsonc
{
  "ok": false,
  "error_kind": "needs_auth"|"stale_token"|"rate_limited"|"upstream_error"|"config_missing",
  "message": "<human readable>",
  "retry_after_seconds": <int>|null,
  "auth_url":             null               // not yet wired (v3 follow-up)
}
```

## INDMoney's actual MCP surface

`tools/list` returns 14 tools. We only consume the first two; the rest are
catalogued for future use.

| Tool | Inputs | Used by us |
|---|---|---|
| `networth_snapshot` | none | ✅ (holdings tool, once per refresh) |
| `networth_holdings` | `asset_type` (enum) | ✅ (per-asset-type loop) |
| `networth_allocation_breakdown` | one asset type | — |
| `indian_stocks_sips` | none | — |
| `mf_sips` | none | — |
| `user_watchlist` | none | — |
| `lookup_ind_keys` | name / partial | — (would unlock ticker mapping; v3 idea) |
| `get_indian_stocks_ohlc` | (TBD) | — (we use yfinance/AKShare for prices) |
| `get_indian_stocks_details` | (TBD) | — |
| `get_indian_stocks_option_chain` | (TBD) | — |
| `get_indian_stocks_greeks_history` | (TBD) | — |
| `get_us_stocks_details` | (TBD) | — |
| `get_mf_funds_details` | scheme id | — |
| `get_mf_by_category` | category slug | — |

**`asset_type` enum:** `IND_STOCK`, `MF`, `US_STOCK`, `BOND`, `EPF`, `NPS`,
`SA`, `FD`, `CRYPTO`, `INSURANCE`, `VEHICLE`, `RE`, `RD`, `AIF`, `PMS`, `PPF`.
Set `INDMONEY_ASSET_TYPES` to a comma-separated subset; default is the three
most users actually hold (`IND_STOCK,US_STOCK,MF`).

## Real-world quirks (the surprises)

Every one of these cost a debug cycle during the live smoke. They're
documented in tests so future work doesn't re-discover them.

1. **Transport on 200 responses is Server-Sent Events**, not plain JSON.
   `event: message\ndata: {jsonrpc...}\n\n`. The client `_parse_mcp_response_body`
   tries plain JSON first and falls back to extracting `data:` lines.
   Two regression tests in `test_indmoney_client.py`.

2. **Single-currency INR throughout.** US stock holdings ship with prices
   in INR (Seagate at ~₹72,000/unit, etc.). No `currency` field, no FX
   field, no USD line. `Holding.currency` is hard-coded to `"INR"` in the
   normalizer.

3. **No ticker symbols.** Holdings come back with `investment_code` (an
   INDMoney internal numeric ID like `"112192"`) and `investment` (the full
   company name). `Holding.symbol = investment_code`. Mapping
   `"DigitalOcean Holdings, Inc." → "DOCN"` is a separate concern; pair
   with `lookup_ind_keys` if you need it.

4. **No transaction history.** `tools/list` has no `get_transactions`
   analog. The whole v1 `IndMoneyTransactionsTool` was deleted in PR #2.
   Trade-journal FIFO PnL still requires manual broker-statement upload —
   pull a CSV/PDF from INDMoney's app and feed it to `trade_journal_tool`.

5. **Errors come back as `{"isError": true}`** inside an otherwise-200
   JSON-RPC envelope, not via JSON-RPC's `error` field. `_unwrap_tools_call_result`
   detects this and raises `UpstreamError`.

6. **Token endpoint is `/token`, not `/oauth/token`.** v1 hardcoded the
   wrong URL and got 403 on every refresh. RFC 8414 well-known metadata is
   the source of truth — `https://mcp.indmoney.com/.well-known/oauth-authorization-server`
   advertises `token_endpoint: "https://mcp.indmoney.com/token"`.

7. **Token endpoint is a confidential client.** `client_secret_post` /
   `client_secret_basic` only — there's no `none` auth method. Refresh
   POSTs MUST include `client_id` + `client_secret` from
   `~/.vibe-trading/indmoney/client.json`.

8. **Some legacy positions return `"unknown"` (literal string) for monetary
   fields** like `invested_amount`. The normalizer's `_to_float()` helper
   coerces silently to `0.0` instead of raising.

9. **`account_id` is always `"default"`.** The token response has no `sub`
   or `account_id` claim. Cache keys collapse to `default:<kind>:<key>`
   for every user; multi-account fan-out is not supported.

10. **MCP also serves a multi-paragraph "instructions" string** on
    `initialize` that asks clients to "frame everything in terms of
    INDmoney" and not name competing brokers. We surface but don't enforce
    that; just be aware it exists if you wonder why the system prompt looks
    branded.

11. **Behind Cloudflare** (`server: cloudflare`, `cf-ray`, `__cf_bm` cookie).
    The client uses one `httpx.Client` per tool invocation so the bot-
    management cookie + TLS session stick across `call_tool` / `refresh` /
    retry. Don't refactor toward a one-client-per-request model.

## Bug fixes journey

This is the order things broke and got fixed during PR #2 (live alignment).
Useful when reading `git log` and wondering "why was this changed?":

| Commit (after PR #2 merge) | Problem | Fix |
|---|---|---|
| `1a3549b` | `resp.json()` raised on every 200 because the body was SSE-framed | Added `_parse_mcp_response_body()` that handles both plain JSON and `event: message / data: {...}` |
| `2289d1c` | MCP errors came back as `isError: true` envelopes; we were returning the error string as if it were data | `_unwrap_tools_call_result` raises `UpstreamError` on `isError` |
| `3f448df` | Token refresh failed — INDMoney is a confidential client and we sent only `grant_type` + `refresh_token` | Added `ClientCredentials.load()` from `~/.vibe-trading/indmoney/client.json`; `_refresh_http` includes `client_id` + `client_secret` |
| `6873973` | Old normalizer assumed `get_holdings` / `get_account` payload shapes that don't exist | Added `normalize_networth_snapshot()` and `normalize_networth_holdings(asset_type, payload)` |
| `db90e7f` | Holdings tool called the wrong tool names | Rewrote `execute()` to call `networth_snapshot` once + loop over `INDMONEY_ASSET_TYPES` |
| `b04dc43` | `IndMoneyTransactionsTool` had no upstream support | Deleted the tool, fixtures, tests, and the events-CSV pipeline; sync tool simplified to "force-refresh holdings" |
| `8603d98` | Refresh hit `/oauth/token` (returns 403) instead of `/token`; some real holdings have `"unknown"` strings in monetary fields | Switched URL default; added defensive `_to_float()` across the normalizer |

## Manual smoke recipe (post-merge sanity check)

```bash
# 1. Confirm token + client credentials are present and not expired
/tmp/venv/bin/python -c "
import sys, time
sys.path.insert(0, 'agent')
from src.integrations.indmoney.auth import TokenCache, ClientCredentials
t = TokenCache().load()
c = ClientCredentials.load()
print('token_present:', t is not None, 'expired:', t.is_expired() if t else None)
print('client_id_present:', bool(c.client_id), 'client_secret_present:', bool(c.client_secret))
"

# 2. Fetch live holdings (force_refresh skips the 15-min cache)
/tmp/venv/bin/python -c "
import sys, json
sys.path.insert(0, 'agent')
from src.tools.indmoney_holdings_tool import IndMoneyHoldingsTool
out = json.loads(IndMoneyHoldingsTool().execute(force_refresh=True))
print('ok:', out.get('ok'), '| holdings:', len(out.get('holdings', [])))
print('error_kind:', out.get('error_kind'))  # populated only on failure
"

# 3. Inspect the audit log for both successful and failed calls
tail -5 agent/uploads/indmoney/audit.log
```

If step 2 fails with `error_kind: stale_token`, the refresh chain has been
broken (refresh tokens are single-use and rotate). Re-run
`python scripts/indmoney_oauth.py` to start a new chain.

## Known limitations / v3 follow-ups

These didn't block PR #2 but are tracked here so future work knows the gaps:

1. **Remote-caller gate is best-effort.** `gate_ok()` reads
   `VIBE_TRADING_REMOTE_CALL=1`, but `agent/api_server.py` and
   `agent/mcp_server.py` don't set it per-request. The proper fix is
   registry-level filtering parallel to the `include_shell_tools` pattern
   in `agent/src/tools/__init__.py::build_registry()`.

2. **`auth_url` field is structurally present on `needs_auth` envelopes
   but always `None`.** A pointer string ("Run: `python scripts/indmoney_oauth.py`")
   would close the loop with the spec's promise.

3. **Token endpoint URL is hardcoded** rather than discovered dynamically
   from the RFC 8414 metadata. Worked once we fixed the constant, but a
   discovery-on-startup pass would be more robust if INDMoney ever moves
   it.

4. **Ticker mapping** (`investment_code` / company name → ticker symbol).
   The `lookup_ind_keys` MCP tool likely helps; not yet wired in.

5. **Single-account assumption.** If INDMoney ever issues tokens with a
   `sub` claim or exposes a `list_accounts` call, the cache-key prefix
   needs to flow that through.

6. **The MCP's market-data tools** (Indian OHLC, options Greeks, US stock
   details) aren't wired. They duplicate yfinance/AKShare for global names
   but unlock NSE/BSE-specific data we don't have today. Optional.

## Reference docs

- **Design spec** (v2-amended): [`docs/superpowers/specs/2026-05-07-indmoney-integration-design.md`](superpowers/specs/2026-05-07-indmoney-integration-design.md)
- **Discovery notes** (post-OAuth findings): [`docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md`](superpowers/specs/2026-05-07-indmoney-discovery-notes.md)
- **Original 14-task plan** (frozen, executed): [`docs/superpowers/plans/2026-05-07-indmoney-integration.md`](superpowers/plans/2026-05-07-indmoney-integration.md)
- **User-facing README** (setup + envelope): [`agent/src/integrations/indmoney/README.md`](../agent/src/integrations/indmoney/README.md)
