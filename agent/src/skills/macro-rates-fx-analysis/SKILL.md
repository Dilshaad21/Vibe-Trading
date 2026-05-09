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
