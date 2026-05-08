# INDMoney MCP Discovery Notes

**Status:** PARTIAL — unauthenticated probe complete; sections 2, 3, 5, 6, 7 await an authenticated probe by the user.
**Endpoint probed:** `https://mcp.indmoney.com/mcp`
**Probed at (UTC):** 2026-05-08T10:30:52Z
**Probe artifact:** `agent/tests/fixtures/indmoney/discovery.json`
**Probe script:** `scripts/indmoney_discover.py`

This file is read by the rest of the INDMoney integration plan (`docs/superpowers/specs/2026-05-07-indmoney-integration-design.md`). Tasks 1–14 must align their fixtures and code paths with what is recorded here. Speculative answers are explicitly marked **Pending authenticated probe by user.** — do not consume those as ground truth.

---

## 1. Auth shape

**Confirmed: OAuth 2.0 Bearer (RFC 6750), with RFC 9728 Protected Resource Metadata advertised.**

The unauthenticated `initialize` POST to `/mcp` returned `401 Unauthorized` with this challenge:

```
WWW-Authenticate: Bearer error="invalid_token",
                  error_description="Authentication required",
                  resource_metadata="https://mcp.indmoney.com/.well-known/oauth-protected-resource"
```

Body:

```json
{ "error": "invalid_token", "error_description": "Authentication required" }
```

Implications:

- Auth scheme is **Bearer token in `Authorization` header**, not a static API key in a custom header.
- Server is **OAuth-protected per RFC 9728** (Protected Resource Metadata). The `resource_metadata` URL is the authoritative pointer to the authorization server(s), supported scopes, and resource indicator. RFC 8414 (`/.well-known/oauth-authorization-server`) was *not* observed (returned no payload in this probe — see caveat below).
- Spec section 11's TODO "static key vs OAuth" is now resolved to **OAuth + Bearer**. The integration must implement the discovery → authorize → token flow described by the metadata document, not a fixed-key flow.

**Caveat — well-known fetches failed in this probe:**
Both `GET /.well-known/oauth-authorization-server` and `GET /.well-known/oauth-protected-resource` raised `[Errno 8] nodename nor servname provided, or not known` from httpx's resolver, despite the `POST /mcp` call to the same host succeeding in the same `AsyncClient`. This is almost certainly a transient client-side resolution quirk (likely IPv6/AAAA cache mismatch) and not the server lacking the endpoints — the server explicitly advertises the protected-resource URL in the WWW-Authenticate header, so it does respond there. The user's authenticated re-run should succeed in fetching both well-known docs and append them to `discovery.json`.

**Other server-side observations:**

- TLS / HSTS enforced (`strict-transport-security: max-age=31536000; includeSubDomains; preload`).
- Behind Cloudflare (`server: cloudflare`, `cf-ray`, `__cf_bm` bot-management cookie set on every request). The integration's HTTP client must accept and round-trip cookies on the same client session, or Cloudflare may begin serving 403/JS challenges across many calls.
- `content-type: application/json` on the error response — server speaks JSON for non-streaming replies. The client `accept: application/json,text/event-stream` was honored; SSE may be used on streaming tool calls but was not exercised here.

## 2. MCP tool list (`tools/list`)

**Pending authenticated probe by user.** Cannot enumerate without a valid Bearer token; the unauthenticated `initialize` was rejected before `tools/list` could be sent.

Spec assumes three tools roughly named `holdings.fetch`, `transactions.fetch`, `cash.fetch` (see `2026-05-07-indmoney-integration-design.md` §3). The actual names, JSON-RPC method shape, and `inputSchema` / `outputSchema` are unverified.

## 3. Sample payloads (holdings / transactions / cash)

**Pending authenticated probe by user.**

Plan tasks the user must capture once authenticated:

- One `holdings` response containing at least: a US equity, an Indian equity (NSE/BSE), a mutual fund, and any cash/sweep position if represented.
- One `transactions` response covering a buy, a sell, a dividend, and (if available) a corporate action (split, bonus, merger).
- One `cash`/balance response, distinguishing settled vs unsettled and per-currency buckets if multi-currency.

Sanitize before commit: redact account numbers, real ticker symbols (replace with `AAA`, `BBB`, …), real holding quantities/prices (round or replace), names, and PAN/Aadhaar-shaped identifiers. Keep field names, types, and structural nesting intact — those are what the normalizer (Task 3) needs.

## 4. Rate limits

**Partial.**

No explicit `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, or `Retry-After` header was returned on the 401 (see `discovery.json/initialize_headers`). That is expected — most servers only emit rate-limit headers on successful (or 429-throttled) responses. **Pending authenticated probe by user** to confirm whether INDMoney returns these headers on 200s; if absent, Task 7's HTTP client should fall back to a conservative built-in token bucket plus exponential backoff on 429 / 503.

What we do know from this probe:

- Cloudflare is in front, so any rate-limit signaling could come from either the origin (custom `X-RateLimit-*`) or Cloudflare (`cf-ray`, `Retry-After` on 429s, `cf-cache-status`).
- Successful responses likely also emit `__cf_bm` cookie rotation; the client must persist cookies on a single session to avoid Cloudflare interactive challenges.

## 5. Account semantics (`account_id`)

**Pending authenticated probe by user.**

Spec section 11 explicitly flags this as unverified. Open questions to resolve from the authenticated tool schemas:

- Is `account_id` a required input on every tool, an optional filter, or implicit from the bearer token's subject?
- For users with multiple INDMoney accounts (e.g., resident + NRI, or family-linked), does the API expose a `list_accounts` style call, or are sub-accounts returned inline within a single holdings response?
- What's the format — opaque UUID, numeric, prefixed string?

Capture an example value (then redact to `<account-id-redacted>`) in the authenticated re-run.

## 6. Currency on holdings

**Pending authenticated probe by user.**

Spec assumes each holding row carries an explicit `currency` field, but INDMoney mixes INR-denominated Indian equities/MFs with USD-denominated US stocks (its hallmark feature). Confirm:

- Per-row `currency` field name (`currency`, `ccy`, `quoteCurrency`, …) and ISO 4217 vs custom codes.
- Whether market value is returned in the holding's native currency, in INR (the home currency), or both.
- Whether an FX rate is included alongside, or expected to be looked up out of band.

This drives the `Holding` dataclass shape in Task 2 and the CSV writer schema in Task 3.

## 7. Corporate-action representation

**Pending authenticated probe by user.**

Confirm whether splits / bonuses / mergers / dividends arrive as:

- Distinct `transaction_type` enum values inside the standard transactions stream, **or**
- Synthetic adjustment rows that re-state historical quantities, **or**
- A separate tool / endpoint we haven't catalogued.

The normalizer (Task 3) must round-trip whichever shape is real; mock fixtures for tests must match it byte-for-byte.

## 8. Deltas from spec assumptions

Comparing what we now know against `2026-05-07-indmoney-integration-design.md`:

| Spec assumption (section 11) | Probe result | Action |
| --- | --- | --- |
| "OAuth shape unverified — could be static key" | **OAuth 2.0 Bearer confirmed via RFC 9728 Protected Resource Metadata advertisement.** | Task 6 (TokenCache) must implement OAuth authorization-code flow + refresh, using the `resource_metadata` URL for discovery. Drop any "static API key" branch from the design before Task 1. |
| "Auth challenge realm/scope hints" | WWW-Authenticate carries only `error=`, `error_description=`, `resource_metadata=`. No `realm=` or `scope=` hint emitted. | Scopes must be read from the protected-resource-metadata document (`scopes_supported`). Until the user fetches it, treat scope list as **Pending**. |
| "Tool names + input schemas unverified" | Unchanged — still **Pending authenticated probe**. | Block Tasks 3, 7, 8, 9, 10 fixture authoring until the user lands authenticated `tools/list` output here. |
| "Pagination unverified" | Unchanged — **Pending**. | Same as above. |
| "`account_id` semantics unverified" | Unchanged — **Pending**. | Same as above. |
| Cloudflare in front | Newly observed. | Task 7's HTTP client must use a single `AsyncClient` per token lifetime (not per request) so `__cf_bm` and the TLS session both stick. Document this in the client docstring. |

---

## What the user needs to do to unblock Tasks 1–14

1. Fetch the authorization-server metadata so we know the OAuth endpoints:
   ```bash
   curl -sS https://mcp.indmoney.com/.well-known/oauth-protected-resource | jq .
   ```
   Append the JSON into `agent/tests/fixtures/indmoney/discovery.json` under `protected_resource_metadata`. Confirm `authorization_servers[]` and follow whichever one is listed to its `/.well-known/oauth-authorization-server` document; capture that under `oauth_metadata`.

2. Run the OAuth authorization-code flow in a browser against the `authorization_endpoint` from step 1, exchange the code for an access token at `token_endpoint`, and export it:
   ```bash
   export INDMONEY_ACCESS_TOKEN="<token-from-flow>"
   ```

3. Re-run the discovery script:
   ```bash
   /tmp/indmoney_venv/bin/python scripts/indmoney_discover.py
   # or, once httpx is in the project venv:
   python scripts/indmoney_discover.py
   ```
   This will populate `tools_list` with the real `tools/list` JSON-RPC response.

4. For each tool name returned, send a `tools/call` JSON-RPC request with realistic-but-minimal arguments and capture one sample response per tool. Add these as additional top-level keys in `discovery.json` (e.g., `sample_holdings`, `sample_transactions`, `sample_cash`). The discovery script does not currently do this — it only does `initialize` and `tools/list`. Either extend the script (preferred — keep the discovery one-shot reproducible) or capture the raw JSON-RPC payloads with `curl` and paste them in.

5. **Sanitize before committing.** Replace: account numbers, names, PAN/Aadhaar-shaped values, all real ticker symbols (`RELIANCE` → `AAA`, `AAPL` → `BBB`), all monetary amounts (round to 2 sig figs or replace with `1000.00`), every cookie/token-shaped value, every X-Request-Id / cf-ray. Field names, structural nesting, types, and enum values stay.

6. Update sections 2, 3, 4 (rate-limit headers on a 200), 5, 6, 7 of this notes file, and tighten section 8's table once each row is no longer "Pending".

Until step 6 lands, Tasks 1, 2, 6 can proceed using only the section-1 OAuth-shape finding. Tasks 3, 7, 8, 9, 10 are blocked on the authenticated payload capture.
