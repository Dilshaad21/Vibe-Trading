# INDMoney MCP Discovery Notes

**Status:** Discovery complete (post-OAuth). All sections populated against `https://mcp.indmoney.com/mcp` server `indmcp/1.27.0` on 2026-05-08.
**Endpoint:** `https://mcp.indmoney.com/mcp`
**Probe artifacts:** `agent/tests/fixtures/indmoney/discovery.json`, `scripts/indmoney_discover.py`, `scripts/indmoney_oauth.py`.
**Token:** captured via `scripts/indmoney_oauth.py` and persisted at `~/.vibe-trading/indmoney/token.json` (mode 0600); client credentials at `~/.vibe-trading/indmoney/client.json` (mode 0600).

This file is read by `2026-05-07-indmoney-integration-design.md`. **The findings below diverge significantly from the spec's working assumptions.** A v2 reshape is required to align the tool layer with INDMoney's real API surface.

---

## 1. Auth shape — CONFIRMED OAuth 2.0 Authorization Code + PKCE

**RFC 6749 §4.1 + RFC 7636 PKCE + RFC 9728 Protected Resource Metadata + RFC 7591 Dynamic Client Registration.**

`GET /.well-known/oauth-protected-resource`:

```json
{
  "resource": "https://mcp.indmoney.com/",
  "authorization_servers": ["https://mcp.indmoney.com/"],
  "scopes_supported": ["portfolio:read"],
  "bearer_methods_supported": ["header"]
}
```

`GET /.well-known/oauth-authorization-server`:

| Field | Value |
| --- | --- |
| `issuer` | `https://mcp.indmoney.com/` |
| `authorization_endpoint` | `https://mcp.indmoney.com/authorize` |
| `token_endpoint` | `https://mcp.indmoney.com/token` |
| `registration_endpoint` | `https://mcp.indmoney.com/register` |
| `revocation_endpoint` | `https://mcp.indmoney.com/revoke` |
| `scopes_supported` | `portfolio:read`, `market:read` |
| `response_types_supported` | `code` |
| `grant_types_supported` | `authorization_code`, `refresh_token` |
| `token_endpoint_auth_methods_supported` | `client_secret_post`, `client_secret_basic` (no `none`) |
| `code_challenge_methods_supported` | `S256` |

**Implications confirmed:**
- **Confidential client model.** Token endpoint requires a `client_secret` — both `client_id` AND `client_secret` must be sent on every refresh. This means our `IndMoneyClient._refresh_http` (currently sends only `grant_type` + `refresh_token`) is broken — it does not send the client credentials. **Bug: refresh on 401 will fail in production until we fix this.**
- **Dynamic Client Registration is supported.** No pre-registered `client_id` is needed — we can `POST /register` to obtain one. Our `scripts/indmoney_oauth.py` does this; the credentials need to be persistable for refresh, currently saved to `~/.vibe-trading/indmoney/client.json` outside `TokenCache`. **Follow-up: extend `TokenCache` to hold `client_id` + `client_secret`, or pass them through to `IndMoneyClient` on construction.**
- **PKCE is supported and we use it.** S256 only.
- **`portfolio:read` is the only scope we need** for v1. `market:read` is for market data tools (Indian OHLC, options) — out of scope.
- **Token response observed in the wild does NOT include a `sub` or `account_id` claim.** We fell back to `account_id="default"` in `TokenCache`. Practically, the cache key prefix `<account>:<kind>:<key>` collapses to `default:<kind>:<key>` for every user. Single-account-per-token is the working model.

**TLS + Cloudflare:**
- TLS / HSTS preloaded.
- Behind Cloudflare (`server: cloudflare`, `cf-ray`, `__cf_bm` cookie). Spec section 4 already calls for one `httpx.Client` per tool invocation — keep that.

## 2. MCP tool list — CONFIRMED 14 tools

`tools/list` returned the following. **None of the spec's assumed names (`get_holdings`, `get_account`, `get_transactions`) exist.**

Server identity: `indmcp/1.27.0`. Capabilities: `prompts`, `resources`, `tools`. Server delivers initial-instructions to the client (multi-paragraph English instructions to "frame everything in terms of INDmoney" — a soft branding constraint, not a technical limit).

| # | Tool | Inputs | Purpose |
| --- | --- | --- | --- |
| 1 | `networth_snapshot` | none | Total invested / current / networth + per-asset-type and per-assetclass arrays + sector breakdown. Closest analog to spec's `get_account` / portfolio overview. |
| 2 | `networth_holdings` | `asset_type` (enum, see below) | Row-level holdings for ONE asset type per call. Closest analog to spec's `get_holdings` — but requires N calls (one per asset type) to enumerate the full portfolio. |
| 3 | `networth_allocation_breakdown` | one specific asset type | Sector / market-cap / asset-class slice for one asset type. |
| 4 | `indian_stocks_sips` | none | User's Indian stock SIP plans (Systematic Investment Plans). |
| 5 | `mf_sips` | none | User's mutual-fund SIPs. |
| 6 | `user_watchlist` | none | User's watchlisted instruments. |
| 7 | `lookup_ind_keys` | name / partial | Resolve stock / index / derivative / MF names to internal codes. |
| 8 | `get_indian_stocks_ohlc` | (TBD) | Historical + intraday OHLC for Indian stocks. |
| 9 | `get_indian_stocks_details` | (TBD) | Live Indian stock details. |
| 10 | `get_indian_stocks_option_chain` | (TBD) | Option chain. |
| 11 | `get_indian_stocks_greeks_history` | (TBD) | Options Greeks history. |
| 12 | `get_us_stocks_details` | (TBD) | Live US stock details. |
| 13 | `get_mf_funds_details` | scheme id | Detailed MF data by scheme id. |
| 14 | `get_mf_by_category` | category slug(s) | MF search/ranking. |

**`asset_type` enum** (from a validation error returned for an invalid value, captured 2026-05-08):
`IND_STOCK`, `MF`, `US_STOCK`, `BOND`, `EPF`, `NPS`, `SA`, `FD`, `CRYPTO`, `INSURANCE`, `VEHICLE`, `RE`, `RD`, `AIF`, `PMS`, `PPF`. Note: `STOCK` (which appears in `networth_snapshot` payloads as an aggregate label) is **not** a valid `networth_holdings` argument.

**Critical absence:** there is **no `get_transactions` tool**. INDMoney's MCP does not expose row-level buy/sell transaction history. This means:
- The spec's `indmoney_transactions` tool (Task 9) has no upstream support and cannot be implemented as designed.
- The trade-journal FIFO PnL pipeline (`agent/src/tools/trade_journal_tool.py`) has no automatic feed from this MCP. The user would still need to import a CSV from INDMoney's account statements UI.
- Behavior analysis (disposition effect, overtrading) is similarly without an automatic feed.

## 3. Sample payloads (sanitized)

### `networth_snapshot` (no inputs)

Returns a JSON-encoded **string** wrapped in MCP `text` content:

```jsonc
{
  "total_invested":      <INR>,            // sum across all asset types
  "total_current_value": <INR>,            // current market value
  "total_networth":      <INR>,            // current minus liabilities (loans, EMIs, credit cards)
  "investments": [                         // per asset_type (uses non-canonical labels — e.g. "STOCK" not "IND_STOCK")
    {
      "asset_type":                  "<label>",   // observed: "STOCK", "US_STOCK", "US_STOCK_WALLET", "SA", ...
      "invested_value":              <INR>,
      "current_value":               <INR>,
      "return":                      <INR>,
      "return_percentage":           <number>,
      "progress_value_percentage":   <number>     // share of portfolio, 0..100
    }
  ],
  "assets": [                              // per assetclass_l2 (display label)
    {
      "assetclass_l2":               "<label>",   // observed: "Indian Equity", "Liquid", "Gold", "Global Equity"
      "invested_value":              <INR>,
      "current_value":               <INR>,
      "return":                      <INR>,
      "return_percentage":           <number>,
      "progress_value_percentage":   <number>
    }
  ],
  "sector": [
    { "sector": "<label>", "invested_value": <INR>, "current_value": <INR>, ... }
  ]
}
```

All values are in **INR** (single currency). No per-row currency field; the home currency is implicit.

### `networth_holdings` with `asset_type=US_STOCK`

```jsonc
{
  "holdings": [
    {
      "investment_code": "<INDMoney internal id, e.g. 112192>",
      "investment":      "<full company name, e.g. \"Seagate Technology Public Ltd. Co.\">",
      "asset_type":      "US_STOCK",
      "assetclass_l2":   "Global Equity",
      "invested_amount": <INR>,                  // cost basis in INR
      "market_value":    <INR>,                  // current value in INR
      "holding_percent": <number>,               // share of US-stock sub-portfolio
      "total_pnl":       <INR>,                  // unrealized
      "pnl_per":         <number>,
      "xirr":            <number>,               // 0 when N/A
      "total_units":     <fractional>,           // fractional shares supported
      "unit_price":      <INR per unit>,         // current price in INR (NOT USD even for US stocks)
      "broker":          "INDmoney",
      "market_cap":      "Large Cap" | "Mid Cap" | ...
    }
  ]
}
```

**No ticker symbols.** US stocks are returned as `investment_code` (INDMoney internal ID) + `investment` (full company name). Mapping `"DigitalOcean Holdings, Inc." → "DOCN"` is the integrator's problem — `lookup_ind_keys` may help, but the v1 normalizer will likely have to ship a heuristic.

**Errors come back as a normal MCP envelope with `isError: true`:**
```jsonc
{ "content": [{ "type": "text", "text": "Error executing tool networth_holdings: 1 validation error ..." }],
  "isError": true }
```
The current `IndMoneyClient` does not check `isError`; it should. Currently it would happily unwrap the error string and return it as if it were data.

## 4. Rate limits

- No `X-RateLimit-*` headers observed on either 401 or 200 responses across the probe set.
- `Retry-After` not seen in any response (no 429s observed in this small probe).
- Cloudflare cookies (`__cf_bm`, `__cflb`) cycled normally.
- **Action:** the conservative built-in 429/503 handling already in `IndMoneyClient` (1 retry with 2s backoff, then `UpstreamError`) is appropriate. If we hit Cloudflare interactive challenges in production, log + back off rather than retrying tightly.

## 5. Account semantics — single-account-per-token

The token response includes no `sub` or `account_id` claim. Our OAuth helper falls back to `"default"` for the cache key prefix. There is no `list_accounts` style call in `tools/list`, and no tool takes an `account_id` argument. The bearer token implicitly identifies the user; multi-account fan-out is not supported by this MCP.

**Action:** the spec's `multi-account fan-out` scope-out (section 10) is now permanently correct rather than a future-looking deferral.

## 6. Currency on holdings — single-currency (INR), no FX field

Every monetary value in every payload is INR. US stock holdings ship `invested_amount`, `market_value`, and `unit_price` in INR (not USD). There is no per-row `currency` field, no `fx_rate` field, no quote-currency hint. The home currency is hard-coded INR by the server.

**Implications for our `Holding` dataclass and CSV writers:**
- The spec's `Holding.currency` and `CashSnapshot.cash_usd` / `cash_inr` schema does not match. Real responses give us only INR.
- The `(fx_usd_inr=X)` suffix encoded in `TradeRecord.name` (Task 3) is unreachable — we don't get an FX field to record. If we want USD-denominated PnL for US stocks, we'd need to do FX lookup ourselves or scrape the implicit rate from `market_value / total_units / yfinance_price`.
- The dataclass either needs a v2 redesign (drop `currency`, drop `cash_usd`/`cash_inr`, accept INR everywhere) OR we keep the structure and always set `currency="INR"` and cash split as cash_usd=0/cash_inr=<value>. Latter is less invasive but slightly dishonest about the data.

## 7. Corporate-action representation — N/A

Since `get_transactions` does not exist in this MCP, there is no transaction stream in which corporate actions could appear. The networth payloads expose only point-in-time state (current holdings, current PnL), not history.

If a downstream feature needs split/dividend/merger awareness, it must come from a different source (broker statement upload, yfinance, etc.) — not from this MCP.

## 8. Deltas from spec assumptions

| Spec assumption | Reality | Action |
| --- | --- | --- |
| OAuth shape unverified | **OAuth Authorization Code + PKCE + Dynamic Client Registration confirmed.** | Drop the static-key branch from auth design (already done). |
| Tool names: `get_holdings`, `get_account`, `get_transactions` | **All three names are wrong.** Real names: `networth_snapshot`, `networth_holdings(asset_type=...)`. No transactions tool exists. | Rework `IndMoneyHoldingsTool` to call `networth_snapshot` + `networth_holdings` per asset type (loop). **Drop `IndMoneyTransactionsTool` entirely** (no upstream support); replace its plan-section with a documented limitation. The `IndMoneySyncTool` reduces to "refresh holdings cache" only. |
| Per-row `currency` field, mixed USD/INR holdings | **Single-currency INR throughout.** No FX field. | Update `Holding` schema in v2 reshape: drop `currency` field OR set it always to `"INR"`. Drop `CashSnapshot.cash_usd` field (always 0); rename to a single `cash_inr` field, or keep schema and document the lie. |
| Output is JSON content (`{"type":"json","json":{...}}`) | **Output is text content (`{"type":"text","text":"<JSON-stringified>"}`).** Our `_unwrap_tools_call_result` already handles this branch — confirmed working. | None. |
| Transport on 200 responses is plain JSON | **Transport on 200 is Server-Sent Events** (`event: message\ndata: {...}\n\n`). The `IndMoneyClient` calls `resp.json()` which raises on the SSE body. | **Bug — must be fixed** before the integration can talk to the live server. Parse the SSE frames in `_rpc`, extract the `data:` line, then `json.loads` it. |
| Token refresh sends only `grant_type` + `refresh_token` | **Token endpoint requires `client_secret_post` or `_basic`** — `client_id` AND `client_secret` must accompany the refresh. | **Bug — must be fixed.** `IndMoneyClient.__init__` should accept the client credentials; `_refresh_http` should send them. Persistence of client credentials needs to flow through `TokenCache` (or a new `ClientCredentialsCache`). |
| Errors are surfaced via JSON-RPC `error` field | **Errors are surfaced as `{"content":[...],"isError": true}` with the error string in `text`** — JSON-RPC `error` is *not* used. | `IndMoneyClient._rpc` must check `result.isError` and convert to `UpstreamError`. Currently it would hand the user the error string as if it were data. |
| `account_id` semantics | **No `sub`/`account_id` claim in token; no tool takes an `account_id` argument.** | Single-account assumption confirmed. Use `"default"` as the cache prefix for v1; revisit if a `list_accounts` call ever appears. |

## 9. v2 reshape plan (follow-up PR)

The current branch ships the integration **scaffold** — auth, token cache, MCP HTTP client (with bugs noted above), normalizer, cache, audit log, and three tool stubs against the assumed shapes. **The branch will not successfully fetch INDMoney data until the following follow-up commits land.** Recommended sequence:

1. **Fix the SSE parsing bug** in `agent/src/integrations/indmoney/client.py::_rpc`. Add a small `_parse_sse(text) -> dict` helper that pulls the `data:` line out of an SSE frame; if the body parses as plain JSON, fall back to that. Add a unit test with a captured SSE response.
2. **Fix the refresh-credentials bug.** Wire `client_id` + `client_secret` from `~/.vibe-trading/indmoney/client.json` (or a new field on `Token`) into `IndMoneyClient._refresh_http` so it can actually refresh. Add a unit test using `MockTransport` that asserts the body of the token POST contains both fields.
3. **Detect MCP `isError: true`** in `_unwrap_tools_call_result` and raise `UpstreamError` with the error string. Add a unit test.
4. **Rework `IndMoneyHoldingsTool`** to call `networth_snapshot` once for the cash/total summary, then `networth_holdings(asset_type="US_STOCK")` and `networth_holdings(asset_type="IND_STOCK")` (and `MF`, etc., as configured) and merge. Replace the fixtures in `agent/tests/fixtures/indmoney/` with the sanitized real shapes documented in section 3.
5. **Drop `IndMoneyTransactionsTool` and `IndMoneySyncTool`'s transactions branch.** Update the spec, plan, tool registry tests, and CSV writer tests accordingly. Document the absence of MCP-driven transaction history in the README and point users at INDMoney's account-statements export as the manual fallback.
6. **Reshape `Holding`** to drop `currency` (always INR) and `CashSnapshot` to drop `cash_usd` (always zero from this source). Or keep the dataclasses and document the always-INR constraint at the boundary — judgment call.
7. **Rename or repurpose `IndMoneySyncTool`** as `IndMoneyRefreshTool` — its only job after the reshape is "force-refresh the holdings cache".
8. **Optional v2.1: market-data tools.** If desired, expose `get_indian_stocks_ohlc`, `get_us_stocks_details`, `lookup_ind_keys` as separate Vibe-Trading tools to unlock Indian market data inside the agent. Out of scope for the read-only-portfolio v1 reshape.
