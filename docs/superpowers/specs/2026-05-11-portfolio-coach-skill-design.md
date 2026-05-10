# Portfolio-coach skill — design

Date: 2026-05-11
Status: design (pre-implementation)

## Overview

A new project skill that acts as a decision framework + cadence-based monitoring
checklist for portfolio management. It routes user questions to the right
specialist skill from the existing 74-skill registry and provides
daily/weekly/monthly/quarterly watch lists tuned to balance profit-seeking
with portfolio stability.

It complements the three existing recipe skills (`portfolio-rebalance`,
`macro-rates-fx-analysis`, `equity-fundamental-deep-dive`) — those each
**run** one specific analysis end-to-end; `portfolio-coach` **routes** to
them and gives the user the calendar of things to watch in between.

## Motivation

A user with a real INDMoney portfolio and 74 skills available has a discovery
problem: which skill answers their current question, and what should they be
monitoring on an ongoing basis? Today the LLM answers this implicitly through
the system prompt's skill descriptions. That works for explicit questions
("run a backtest"), but breaks down for vague portfolio prompts ("how can I
improve my returns?") where multiple skills apply and the user also needs a
monitoring rhythm, not just one answer.

`portfolio-coach` makes that routing + cadence guidance explicit, repeatable,
and tunable.

## Brainstorming decisions

| Decision | Choice |
|---|---|
| Skill role | Decision framework + follow-up checklist (not pure router, not full orchestrator) |
| Routing scope | ~25–30 portfolio-relevant skills (excludes hyper-specific tools) |
| Follow-up shape | Tiered by cadence (daily/weekly/monthly/quarterly + trigger overrides) |
| Approach | Playbook with optional live-context anchor (Approach B) |
| Name | `portfolio-coach` |
| Category | `recipe` |

## Skill identity

```
agent/src/skills/portfolio-coach/SKILL.md   ← new file
```

Frontmatter:

```yaml
---
name: portfolio-coach
description: Decision framework + cadence-based monitoring checklist for portfolio management. Routes user questions to the right specialist skill (portfolio-rebalance, risk-analysis, hedging-strategy, etc.) and provides daily/weekly/monthly/quarterly watch lists tuned for max-profit + stability. Optionally anchors guidance to live INDMoney holdings.
category: recipe
---
```

## Skill body structure

Top-level headings:

1. `# Portfolio coach recipe`
2. `## When to use`
3. `## Inputs` (no required inputs; optional INDMoney holdings)
4. `## Steps`
   1. Optional: pull live context via `indmoney_holdings()`
   2. Identify user intent → consult routing table
   3. Apply cadence framework
   4. Synthesise: routed-skills-to-load + tailored watch list
5. `## Routing table`
6. `## Cadence framework`
7. `## Profit-vs-stability principles`
8. `## Failure modes`

## Routing table (final content)

Organised by user-intent theme. Final table has ~25 rows.

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
| Stock | "Screen for value / quality / growth stocks" | `fundamental-filter` | PE/PB/ROE multi-metric screen |
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
| Strategy | "Build a multi-factor model" | `factor-research` (+ `multi-factor`) | IC/IR + ranking |
| Performance | "What drove my returns?" | `performance-attribution` | Brinson decomposition |
| Compliance | "Tax / regulatory rules for [market]?" | `regulatory-knowledge` | A-share/HK/US/crypto rules |

**Disambiguation rule:** when a question hits two themes, primary skill comes
from the table column; the secondary check is the next theme's most-relevant
skill. Example: "should I trim my big tech bet for stability?" → primary
`portfolio-rebalance`, secondary `risk-analysis`.

**Default fallback:** if no row matches, route to `portfolio-rebalance` +
`risk-analysis` as a safe default pair.

## Cadence framework (final content)

### Daily (≤5 min)
- Price moves >±5% on any holding (immediate flag for employer stock)
- Earnings calendar — any holding reporting today/tomorrow
- Top-5 position news scan
- USD/INR daily move (>±1% for INR-denominated investors)
- Volatility regime: VIX <20 normal, 20–25 caution, >25 pause new buys

### Weekly (≤30 min)
- Sector rotation: leaders/laggards vs your sector exposure
- Macro releases due (CPI, FOMC, jobs, RBI MPC)
- Relative strength: top winners/losers vs S&P 500 / NIFTY 50
- Idle cash check — any uninvested wallet balance
- New analyst rating actions on holdings
- Upcoming earnings (next 1–2 weeks)

### Monthly (≤1 hour)
- Concentration drift — any single position now >12%?
- Correlation matrix — has portfolio become more correlated?
- Sector exposure vs targets (drift >5% per sector)
- Performance attribution — what drove returns vs benchmark
- Drawdown vs personal threshold
- FX impact decomposition — stock move vs FX move

### Quarterly (full review, ~3 hours)
- Full rebalance to target weights → call `portfolio-rebalance`
- Risk re-baseline → call `risk-analysis`
- Behavioural audit → call `shadow-account` if trade history available
- Macro thesis check → call `macro-rates-fx-analysis`
- Hedging review → call `hedging-strategy`
- Tax-loss harvesting candidates
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

Three explicit rules in the skill body:

1. **Stability is the constraint, profit is the objective.** When
   recommendations conflict, stability wins. No single position >12%, no asset
   class >65%, no single sector >35%.
2. **Skew daily/weekly toward profit signals; monthly/quarterly toward
   stability checks.** Cadence already encodes this — daily watches catch
   moves and momentum; monthly reviews enforce concentration and correlation
   discipline.
3. **Macro regime adjusts the skew.** Low VIX + broad bull → can lean profit.
   High VIX or late-cycle → lean stability. Geopolitical crisis → stability
   and hedge first.

## Failure modes

- `indmoney_holdings()` returns auth error or empty: still produce generic
  framework + cadence; explicitly note the tailoring is missing.
- User's question doesn't match the routing table: fall through to default
  pair `portfolio-rebalance` + `risk-analysis`.
- The skill **routes to** specialist skills; it does not replace them. It
  must not produce VaR numbers, rebalance weights, or DCF outputs itself —
  always defer to the specialist for those.

## Testing

Single edit to `agent/tests/test_recipe_skills_loadable.py`:

```python
_RECIPE_SKILLS = {
    "macro-rates-fx-analysis",
    "portfolio-rebalance",
    "equity-fundamental-deep-dive",
    "portfolio-coach",  # NEW
}
```

Existing tests cover: loaded by `SkillsLoader`, has `category: recipe`,
displays in correct order. The `test_recipe_load_skill_returns_full_body`
test is `macro-rates-fx-analysis`-specific — leaving it untouched.

## Verification before commit

Before claiming done:

1. `pytest agent/tests/test_recipe_skills_loadable.py -q` — fast, scoped.
2. `ruff check agent` — lint.
3. Verify the new skill body loads — confirm `SkillsLoader.get_content("portfolio-coach")` returns non-empty content.

## Commit & push protocol

- **Branch**: create `feat/portfolio-coach-skill` from `main`. Matches the
  pattern from recent merges (`feat/mcp-llm-boundary`).
- **Commit message** (Conventional Commits):

  ```
  feat(skills): add portfolio-coach decision-framework skill

  Routes user portfolio questions to the right specialist skill
  (portfolio-rebalance, risk-analysis, hedging-strategy, etc.) and
  provides daily/weekly/monthly/quarterly watch lists tuned for
  max-profit + stability. Optionally anchors guidance to live
  INDMoney holdings.
  ```

- **Push**: to `origin` only (the user's fork at `git@github.com:Dilshaad21/Vibe-Trading.git`), not to `upstream`.
- **PR**: not opened automatically. Will offer as a follow-up.

## Out of scope

- Rewriting any existing recipe skill.
- Adding new categories beyond `recipe`.
- Including hyper-specific skills like `vnpy-export`, `pine-script`,
  `chanlun`, `ashare-pre-st-filter`, A-share-only flow tools, or
  crypto-specific skills (`onchain-analysis`, `defi-yield`,
  `stablecoin-flow`, `liquidation-heatmap`, `perp-funding-basis`,
  `token-unlock-treasury`, `crypto-derivatives`) in the routing table.
- Extending the existing test file beyond adding `portfolio-coach` to the
  recipe-skills set.
- Opening a pull request — only commit + push to fork.

## Follow-ups (post-merge candidates)

- Add a routing-table-coverage test that asserts every skill referenced in
  the routing table actually exists in the registry (would catch typos and
  rename rot).
- Consider adding asset-class-specific routing addenda (e.g., a separate
  `crypto-coach` or `india-coach`) if user demand emerges.
- Extend the trigger-override table with personal thresholds (drawdown
  tolerance, FX hedge ratio) once the user articulates them.
