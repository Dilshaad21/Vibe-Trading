# INDMoney MCP Integration

Read-only INDMoney portfolio access. Pulls holdings via the live
`mcp.indmoney.com/mcp` server (server identity `indmcp/1.27.0`) and
exposes the data through Vibe-Trading's tool registry.

> **v2 reshape complete.** The earlier scaffold assumed tool names
> (`get_holdings` / `get_account` / `get_transactions`) that don't exist
> on the live server. The current code targets the real tool surface
> (`networth_snapshot`, `networth_holdings`). See
> `docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md` for
> the full discovery write-up.

## One-time setup

```bash
pip install -e ".[dev]"

# Run the OAuth helper once. It does Dynamic Client Registration
# (RFC 7591), drives Authorization Code + PKCE via a local 127.0.0.1
# loopback, and writes:
#   ~/.vibe-trading/indmoney/client.json   (client_id + client_secret)
#   ~/.vibe-trading/indmoney/token.json    (access_token + refresh_token)
# Both files are mode 0600.
python scripts/indmoney_oauth.py
```

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `INDMONEY_MCP_URL` | `https://mcp.indmoney.com/mcp` | Override for staging |
| `INDMONEY_TOKEN_URL` | `https://mcp.indmoney.com/token` | OAuth token endpoint (matches the RFC 8414 well-known metadata) |
| `INDMONEY_TOKEN_PATH` | `~/.vibe-trading/indmoney/token.json` | Token store (mode 0600) |
| `INDMONEY_ASSET_TYPES` | `IND_STOCK,US_STOCK,MF` | Comma-separated asset types fetched per refresh. Valid values: `IND_STOCK`, `MF`, `US_STOCK`, `BOND`, `EPF`, `NPS`, `SA`, `FD`, `CRYPTO`, `INSURANCE`, `VEHICLE`, `RE`, `RD`, `AIF`, `PMS`, `PPF` |
| `INDMONEY_HOLDINGS_TTL_SECONDS` | `900` | Holdings cache TTL (15 min) |
| `VIBE_TRADING_ENABLE_INDMONEY` | unset | Best-effort gate for non-loopback API/MCP-SSE callers (see Known limitations) |

## Tools (auto-published via the registry)

| Tool | What it does |
|---|---|
| `indmoney_holdings` | Calls `networth_snapshot` once for totals + cash proxy, then `networth_holdings(asset_type=X)` for each `INDMONEY_ASSET_TYPES` entry. Returns a unified `holdings` array, per-asset-type investment breakdown, per-class assets breakdown, sector breakdown, and a `cash` summary. Cache-first (TTL 15 min); pass `force_refresh=true` to skip. |
| `indmoney_sync` | Force-refresh wrapper around `indmoney_holdings`. Also prunes snapshots older than 30 days. Use after broker activity to bring the cache up to date. |

## Response shape (envelope)

```jsonc
{
  "ok": true,
  "asof": "",
  "account_id": "default",                     // INDMoney does not return a sub claim
  "asset_types": ["IND_STOCK","US_STOCK","MF"],
  "currency":    "USD",                        // "USD" when conversion on (default), else "INR"
  "usdinr_rate": 88.0,                          // INR per USD used for conversion; null if off
  "totals": {
    "total_invested":      <USD|INR>,
    "total_current_value": <USD|INR>,
    "total_networth":      <USD|INR>
  },
  "investments_by_asset_type": [...],          // money fields converted when currency=="USD"
  "assets_by_class":          [...],
  "sector_breakdown":         [...],
  "holdings": [
    {
      "symbol":         "<INDMoney investment_code, e.g. '112192'>",
      "name":           "<full company name>",
      "quantity":       <fractional units>,
      "avg_cost":       <USD|INR per unit>,
      "market_value":   <USD|INR>,
      "unrealized_pnl": <USD|INR>,
      "currency":       "USD",                 // matches top-level currency; see Known limitations
      "asset_class":    "us_equity"|"indian_equity"|"mf"|"other",
      "asof":           ""
    }
  ],
  "cash": {
    "cash_usd":               <USD>,           // Liquid proxy lands here when conversion on
    "cash_inr":               <INR>,           // ...or here when conversion off
    "pending_settlement_usd": 0.0,
    "asof":                   ""
  },
  "snapshot_path": "<path under agent/uploads/indmoney/>",
  "from_cache":    false
}
```

On failure the response is the structured envelope:

```jsonc
{
  "ok": false,
  "error_kind": "needs_auth"|"stale_token"|"rate_limited"|"upstream_error"|"config_missing",
  "message": "<human readable>",
  "retry_after_seconds": <int>|null,           // populated for rate_limited
  "auth_url":             null                 // see Known limitations #4
}
```

## Output files

All cache + snapshot files land under `agent/uploads/indmoney/` (already
inside the project's default sandbox roots — no allow-list change needed):

```
agent/uploads/indmoney/
├── .index.json                              # cache freshness index
├── audit.log                                # one line per MCP call
├── <account>.lock                           # transient per-account fetch lock
└── <account>_holdings_<ts>.json             # holdings snapshot
```

There is no transactions CSV / events CSV — INDMoney's MCP server has
no transaction-history endpoint, so the v1 trades-vs-events pipeline
was dropped in v2 #6. If you need FIFO PnL pairing, import an INDMoney
account-statement CSV/PDF manually and feed it to `trade_journal_tool`.

## Known limitations

1. **No transaction history.** INDMoney's MCP exposes no
   `get_transactions` analog (verified against `tools/list` on
   2026-05-08). Trade-journal FIFO PnL and behavior analysis cannot be
   auto-fed from the MCP. Manual statement import remains the only
   path. Tracked in discovery notes section 2.

2. **No ticker symbols.** `Holding.symbol` is INDMoney's internal
   `investment_code` (e.g. `"112192"`). Ticker resolution (mapping
   `"DigitalOcean Holdings, Inc."` → `"DOCN"`) is a separate concern.
   Pair this integration with `lookup_ind_keys` (also exposed by the
   same MCP — not yet wired into Vibe-Trading) or maintain a manual
   mapping if you need to cross-reference yfinance prices.

3. **Source is single-currency (INR); USD is converted out-of-band.**
   Even US stock holdings are priced in INR — INDMoney converts at the
   server and exposes no per-row currency field, no FX rate, no USD line.
   To present USD, the tool fetches a USD/INR rate from Yahoo Finance
   (`USDINR=X`, via `fx.get_usdinr_rate`) and divides the INR money
   fields by it. Conversion is **on by default**; set
   `INDMONEY_CONVERT_TO_USD=0` to keep raw INR, or pin the rate with
   `INDMONEY_USDINR_RATE=<inr_per_usd>` (skips the live lookup). The
   active rate and currency are echoed in the snapshot as `usdinr_rate`
   and `currency`. Note the converted USD is an approximation: it uses a
   single spot rate, not INDMoney's internal per-trade FX.

4. **Remote-caller gate is best-effort.** `gate_ok()` in
   `indmoney_holdings_tool.py` checks `VIBE_TRADING_REMOTE_CALL=1`,
   but `agent/api_server.py` and `agent/mcp_server.py` don't currently
   set that variable per-request — so the gate is non-functional in
   production today. The proper fix mirrors the existing shell-tools
   pattern (`include_shell_tools` in
   `agent/src/tools/__init__.py::build_registry`); track as a follow-up
   PR. The integration is safe in practice because the OAuth token
   lives at `~/.vibe-trading/indmoney/token.json` on the user's
   machine — a remote attacker gets `error_kind: needs_auth`, not
   data — but users running the API server on a public interface
   should consider the gate non-functional.

5. **`auth_url` is always `None` on `needs_auth`.** The spec promised
   a populated `auth_url`; the current implementation lives in the
   CLI / OAuth helper. A follow-up may populate the field with a
   pointer string ("Run: python scripts/indmoney_oauth.py").

6. **`account_id` is always `"default"`.** INDMoney's token response
   has no `sub` claim, so multi-account fan-out is not supported. The
   cache-key prefix collapses to `default:<kind>:<key>` for every
   user.
