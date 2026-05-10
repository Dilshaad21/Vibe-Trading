---
name: portfolio-coach
description: Decision framework + cadence-based monitoring checklist for portfolio management. Routes user questions to the right specialist skill (portfolio-rebalance, risk-analysis, hedging-strategy, etc.) and provides daily/weekly/monthly/quarterly watch lists tuned for max-profit + stability. Optionally anchors guidance to live INDMoney holdings.
category: recipe
---

# Portfolio coach recipe

## When to use

- User asks a vague portfolio question ("how can I improve my returns?", "what should I do?", "what should I look at?") where multiple specialist skills could apply.
- User wants both an answer to the immediate question AND a monitoring rhythm — what to watch daily / weekly / monthly / quarterly.
- User asks "which skill should I use?" or seems uncertain which tool fits their question.
- Onboarding moment: user is new to the toolkit and needs orientation.

## Inputs

- None required.
- Optional: live INDMoney holdings via `indmoney_holdings()`. If unavailable, produce the generic framework + cadence and explicitly note the tailoring is missing.

## Steps

### 1. (Optional) Pull live context

If the user has an INDMoney portfolio and wants tailored guidance, call `indmoney_holdings()`. Capture:

- `holdings[]` — for top-5 concentration check.
- `totals.total_current_value` — for percent-of-book calculations.
- `cash` — for idle-wallet detection.

If the call returns `error_kind` of `needs_auth` or `stale_token`, skip this step and continue with the generic framework. Do not block the rest of the recipe on auth.

### 2. Identify user intent → consult routing table

Match the user's question against the routing table below. If two themes apply, take primary from the table and secondary from the next-most-relevant theme. If nothing matches, use the default fallback: `portfolio-rebalance` + `risk-analysis`.

### 3. Apply cadence framework

Pick the cadence tier based on the user's apparent need:

- Reacting to specific news / a single price move → daily watches.
- Reviewing the week → weekly watches.
- Doing a routine check-in → monthly watches.
- Full review or rebalance → quarterly watches.

Always also surface any trigger overrides that apply to the user's current state.

### 4. Synthesise

Output a markdown response with:

- **Recommended skills** — 1–3 specialist skills with a one-line "why" each.
- **Watch list** — the cadence-tier checklist, anchored to the user's holdings if Step 1 succeeded.
- **Triggers active now** — any trigger overrides that fire on the user's current state.
- **Profit-vs-stability stance** — which way the macro regime is leaning right now.

## Routing table

| Theme | User question pattern | Recommended skill(s) | Why |
|---|---|---|---|
| Structure | "Am I too concentrated?" / "Should I rebalance?" / "Give me target weights" | `portfolio-rebalance` | Diagnoses concentration + recommends weights |
| Structure | "Are my holdings too correlated?" / "Am I diversified?" | `correlation-analysis` | Co-movement and cluster detection |
| Structure | "Hedge my employer / single-stock exposure" | `hedging-strategy` (+ `portfolio-rebalance`) | Beta hedge, option protection design |
| Structure | "How should a [age/profile] investor allocate?" | `asset-allocation` | MPT / Black-Litterman / risk budgeting |
| Risk | "What's my VaR / drawdown / stress test?" | `risk-analysis` | VaR, CVaR, Monte Carlo |
| Risk | "Audit my trading patterns / behavioural biases" | `shadow-account` (+ `trade-journal`) | Behavioural fingerprint of actual trades |
| Risk | "Why do I keep losing on / regret my [pattern]?" | `behavioral-finance` (+ `shadow-account`) | Bias checklist + behavioural audit |
| Stock | "Hold or sell [TICKER]?" / "Is [TICKER] a buy?" | `equity-fundamental-deep-dive` | DCF + quality + view |
| Stock | "Is [TICKER] cheap or expensive?" | `valuation-model` | DCF / PE-band / EV-EBITDA |
| Stock | "Screen for value / quality / growth stocks" | `fundamental-filter` | PE / PB / ROE multi-metric screen |
| Stock | "Analyst revision trend / earnings estimate?" | `earnings-revision` (+ `earnings-forecast`) | Estimate trends + PEAD |
| Stock | "Insider trades / 10-K risk factors / SEC filings" | `edgar-sec-filings` | SEC filing parser |
| Macro | "Fed / FX / rates / macro backdrop?" | `macro-rates-fx-analysis` | Cross-asset macro view |
| Macro | "Sector rotation signal?" | `sector-rotation` | Cycle + momentum + flows |
| Macro | "Geopolitical risk to my book?" | `geopolitical-risk` | Crisis quantification |
| Macro | "Where are we in the cycle?" | `macro-analysis` (+ `global-macro`) | Cycle positioning |
| Technical | "Entry / exit timing for [TICKER]?" | `technical-basic` (+ `candlestick`, `ichimoku`) | Composite + pattern signals |
| Income | "Build a dividend portfolio" | `dividend-analysis` | Yield quality + sustainability |
| Income | "Pick an ETF" | `etf-analysis` (+ `us-etf-flow` for US) | Cost / tracking / flow signals |
| Income | "Mutual fund selection" | `fund-analysis` | Sharpe, style box, manager evaluation |
| Strategy | "Backtest [idea]" | `strategy-generate` (+ `backtest-diagnose` if it fails) | Codegen + diagnose loop |
| Strategy | "Build a multi-factor model" | `factor-research` (+ `multi-factor`) | IC / IR + ranking |
| Performance | "What drove my returns?" | `performance-attribution` | Brinson decomposition |
| Compliance | "Tax / regulatory rules for [market]?" | `regulatory-knowledge` | A-share / HK / US / crypto rules |

**Default fallback:** if no row matches, route to `portfolio-rebalance` + `risk-analysis`.

## Cadence framework

### Daily (≤5 min)

- Price moves >±5% on any holding (immediate flag for employer stock).
- Earnings calendar — any holding reporting today / tomorrow.
- Top-5 position news scan.
- USD/INR daily move (>±1% for INR-denominated investors).
- Volatility regime: VIX <20 normal, 20–25 caution, >25 pause new buys.

### Weekly (≤30 min)

- Sector rotation: leaders / laggards vs your sector exposure.
- Macro releases due (CPI, FOMC, jobs, RBI MPC).
- Relative strength: top winners / losers vs S&P 500 / NIFTY 50.
- Idle cash check — any uninvested wallet balance.
- New analyst rating actions on holdings.
- Upcoming earnings (next 1–2 weeks).

### Monthly (≤1 hour)

- Concentration drift — any single position now >12%?
- Correlation matrix — has portfolio become more correlated?
- Sector exposure vs targets (drift >5% per sector).
- Performance attribution — what drove returns vs benchmark.
- Drawdown vs personal threshold.
- FX impact decomposition — stock move vs FX move.

### Quarterly (full review, ~3 hours)

- Full rebalance to target weights → call `portfolio-rebalance`.
- Risk re-baseline → call `risk-analysis`.
- Behavioural audit → call `shadow-account` if trade history available.
- Macro thesis check → call `macro-rates-fx-analysis`.
- Hedging review → call `hedging-strategy`.
- Tax-loss harvesting candidates.
- Outright exits — thesis broken on any holding?

### Trigger overrides (act immediately, override cadence)

| Trigger | Action |
|---|---|
| Single position >15% of book | Trim to ≤12% |
| Earnings-day move <-15% on a holding | Review thesis within 48h |
| VIX >30 | Pause new buys, review hedges |
| USD/INR weekly move >3% | Review FX hedge / accelerate USD deployment |
| Employer stock >25% of net worth | Mandatory diversification |
| Any holding -25% from cost | Force reassessment, no averaging-down by default |

## Profit-vs-stability principles

1. **Stability is the constraint, profit is the objective.** When recommendations conflict, stability wins. Hard limits: no single position >12%, no asset class >65%, no single sector >35%.
2. **Skew daily / weekly toward profit signals; monthly / quarterly toward stability checks.** The cadence framework already encodes this — daily watches catch moves and momentum; monthly reviews enforce concentration and correlation discipline.
3. **Macro regime adjusts the skew.** Low VIX + broad bull → can lean profit. High VIX or late-cycle → lean stability. Geopolitical crisis → stability and hedge first.

## Failure modes

- `indmoney_holdings()` returns auth error or empty: still produce the generic framework + cadence; explicitly note the tailoring is missing in the synthesised output.
- User's question doesn't match any row in the routing table: fall through to the default pair `portfolio-rebalance` + `risk-analysis`.
- This skill **routes to** specialist skills; it does not replace them. Never produce VaR numbers, rebalance weights, or DCF outputs in this skill's response — always defer to the specialist for those.
