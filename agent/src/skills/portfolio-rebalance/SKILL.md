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
