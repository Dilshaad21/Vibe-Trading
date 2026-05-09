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
