# Strategy-architect skill — design

Date: 2026-05-11
Status: design (pre-implementation)

## Overview

A new project skill that fuses four analytical dimensions — macroeconomics,
news/catalysts, fundamentals, and technicals — into multi-horizon trade plans
(short / medium / long). Adaptive to input: works on a single ticker, a whole
portfolio, or a theme/sector. Becomes the default entry point for any
"should I buy/hold/sell" or "what's my strategy on X" question.

It complements the four existing recipe skills (`portfolio-coach`,
`portfolio-rebalance`, `macro-rates-fx-analysis`, `equity-fundamental-deep-dive`)
— those each cover one analytical lens or one workflow step;
`strategy-architect` is the one to load when a user wants the most complete
single-shot view across all lenses.

## Motivation

Today, producing a complete strategy in this toolkit means chaining multiple
skills:

1. `macro-rates-fx-analysis` for the macro stance
2. `equity-fundamental-deep-dive` for the fundamental view
3. `technical-basic` for technicals
4. Free-form `web_search` for news/catalysts
5. Manual synthesis into a trade plan

Each step is reasonable in isolation, but the user has to know to chain them,
remember to weight signals by time horizon, and synthesize the conflicts
themselves. That's a discovery + coordination burden.

`strategy-architect` collapses this into a single skill invocation that
produces a complete, horizon-weighted, citation-backed trade plan.

## Brainstorming decisions

| Decision | Choice |
|---|---|
| Input scope | Adaptive — supports ticker, portfolio, and theme inputs |
| Output depth | Full trade plan (verdict + entry + size + stop + exit + monitoring) |
| Time horizon | Multi-horizon adaptive (short 1–4w, medium 1–6m, long 1–3y) |
| News scope | Headlines + analyst notes + earnings/catalysts + macro/geopolitical news (excludes social sentiment) |
| Approach | Inline self-contained (Approach A) — methodology embedded, MCP tools called directly |
| Name | `strategy-architect` |
| Category | `recipe` |

## Skill identity

```
agent/src/skills/strategy-architect/SKILL.md   ← new file
```

Frontmatter:

```yaml
---
name: strategy-architect
description: Comprehensive multi-dimensional analysis recipe. Fuses macroeconomics, news/catalysts, fundamentals, and technicals into multi-horizon trade plans (short/medium/long). Adaptive to input — works on a single ticker, a whole portfolio, or a theme. Default entry point for any "should I buy/hold/sell" or "what's my strategy on X" question.
category: recipe
---
```

## Positioning relative to siblings

| Skill | Role |
|---|---|
| `portfolio-coach` | "What should I look at?" — routes to specialists, cadence checklist |
| `equity-fundamental-deep-dive` | Fundamentals-only deep dive for one ticker |
| `macro-rates-fx-analysis` | Cross-asset macro view |
| `technical-basic` | Technical indicators (used as methodology reference by this skill) |
| **`strategy-architect`** | **Full strategy across all four lenses, multi-horizon** |

Existing recipes are unchanged. This skill becomes the new flagship.

## Dispatch logic

The skill detects input type from the user's question and chooses one of three
paths:

| Input pattern | Path | Examples |
|---|---|---|
| Named single ticker | **TICKER** | "analyze NVDA", "should I buy CEG?" |
| References "my portfolio" / no ticker / generic | **PORTFOLIO** | "what's my strategy?", "how should I position?" |
| Names a theme/sector/idea | **THEME** | "AI infrastructure outlook", "play the weak dollar" |

Ambiguous input → ask one clarifying question; do not guess silently.

## Four analytical dimensions

Each dimension uses MCP tools directly (no chained `load_skill` calls).

| Dimension | Data sources | TICKER framing | PORTFOLIO framing | THEME framing |
|---|---|---|---|---|
| **Macro** | `macro_snapshot()` | Rate sensitivity, FX exposure | Cycle stance, factor tilts | Theme leadership window in cycle |
| **News** | `web_search()` × 3-4 queries; `read_url()` for deeper reads | Earnings date, guidance, analyst revisions, catalysts | Top-3 holdings' catalysts, macro calendar | Theme inflows/outflows, regulatory, headline drivers |
| **Fundamental** | `web_search()` for financials; `factor_analysis()` if available | P/E, P/B, ROE, growth, FCF vs sector | Aggregate book metrics, sector concentration | Theme names' valuation distribution |
| **Technical** | `get_market_data()` for 90-day OHLCV; `pattern_recognition()` if needed | EMA / ADX / RSI / OBV composite (technical-basic methodology) | Top-5 holdings' signals + index regime | Sector ETF technicals (XLK, XLE, IBB, etc.) |

### Sequencing rules

1. **Macro first** — it tints everything else; signal weighting depends on cycle.
2. **News + fundamental + technical run in parallel** — independent inputs.
3. **Synthesis only after all four return** — never produce a partial strategy.

## Synthesis: horizon-weighted signal fusion

Each dimension returns a **signal** (Bullish / Neutral / Bearish) and a
**confidence** (High / Med / Low).

Horizon-specific weights:

| Dimension | Short (1–4w) | Medium (1–6m) | Long (1–3y) |
|---|---|---|---|
| Technical | **40%** | 25% | 15% |
| News / Catalyst | **30%** | 25% | 15% |
| Macro | 20% | 25% | **30%** |
| Fundamental | 10% | 25% | **40%** |

- **Composite signal per horizon:** weighted vote of the four dimensions.
- **Composite confidence:** agreement-weighted (4/4 = High, 3/4 = Med, 2/4 split = Low).
- **Conflict flag:** if any dimension diverges by >1 step from the composite, surface it explicitly — tension is where insight lives.

## Trigger overrides (hard rules)

Override the synthesis regardless of weighted score:

| Trigger | Action |
|---|---|
| RSI > 80 on the position | Trim 25–35% even if composite is Bullish |
| Earnings within 7 days + composite Bullish | Defer new entries until post-print |
| Position already >12% of book | Cap further additions |
| Stop-loss breached | Exit, do not average down |
| Composite Bearish AND down >25% from cost | Exit, do not hope |

## Output template (TICKER path)

```markdown
# Strategy: {TICKER} — {headline + composite verdict}

## Dimensional readout
| Dimension | Signal | Confidence | Top evidence |
| Macro / News / Fundamental / Technical | … | … | … |

## Synthesis
- Composite signal & confidence per horizon
- Conflicts/tensions (1-2 lines, only if dimensions diverge)
- Triggers firing right now (if any)

## Trade plan — Short (1–4 weeks)
- Verdict + conviction
- Entry trigger
- Position size (% of book, $)
- Stop-loss (price, %)
- Exit condition (target / time / signal)
- Top risk

## Trade plan — Medium (1–6 months)
…same structure…

## Trade plan — Long (1–3 years)
…same structure, thesis-based stops not price stops…

## Monitoring
- Daily / Weekly / Monthly items
- Re-run trigger condition

## Sources
- _macro_snapshot fields cited
- web_search URLs cited
- get_market_data window cited
```

### PORTFOLIO path variant

Same top sections. "Trade plan" becomes "Book action plan":
- Top-down stance: sector tilts, cash deployment, hedge needs (per horizon)
- Bottom-up actions: tickers to add / trim / exit with size deltas
- Cash deployment phase plan

### THEME path variant

Same top sections. "Trade plan" becomes:
- Theme thesis + counter-thesis (one-line each)
- Top 3-5 names to express the theme (table with rationale)
- Anti-thesis tickers (what hurts the theme — sell/avoid)
- Allocation envelope per horizon

## Failure modes (graceful degradation)

| Failure | Behavior |
|---|---|
| `macro_snapshot` returns `_errors` populated | Use partial fields; flag gaps; don't block synthesis |
| `indmoney_holdings` returns `needs_auth` (PORTFOLIO path) | Switch to generic-framework mode; tell user to run OAuth |
| `web_search` returns 0 results | Note "no recent news surfaced"; downgrade News confidence to Low; do NOT invent |
| `get_market_data` returns <30 bars | Skip technical composite; output "insufficient history"; Technical → Neutral / Low |
| All four dimensions fail | Refuse to produce a strategy; output explicit failure message |
| Input genuinely ambiguous after one clarifying question | Default to TICKER if a ticker was named; else PORTFOLIO |

## Anti-patterns (explicit DO NOT list in SKILL.md)

- Do **not** produce a strategy from <4 dimensions. If one can't be gathered, say so and reduce confidence — never silently drop a dimension.
- Do **not** invent prices, P/E numbers, or news headlines. Missing values → write "n/a".
- Do **not** recommend a position size that violates `portfolio-coach` trigger limits (>12% single position, >25% employer stock, etc.).
- Do **not** chain to `load_skill` mid-flow. Point user to specialists in output instead.
- Do **not** produce price targets without citing the source.

## Integration

| Existing | Change |
|---|---|
| `portfolio-coach` routing table | Add row: `"Comprehensive analysis / give me a full strategy"` → `strategy-architect` |
| `equity-fundamental-deep-dive` | No change |
| `macro-rates-fx-analysis` | No change |
| `technical-basic` | No change — referenced by Technical dimension methodology |
| `agent/tests/test_recipe_skills_loadable.py` | Add `strategy-architect` to loadable-recipes list (1-line addition) |

## Testing strategy

- **Smoke test:** `load_skill(name="strategy-architect")` returns the SKILL.md content (auto-covered by existing recipe-loadable test).
- **No code paths to test** — this is a markdown methodology doc, not executable code.
- **Manual validation:** after deploy, run three test invocations (one per dispatch path: ticker, portfolio, theme) and inspect output for completeness against the template.

## Size & maintenance trade-off

- Target: ~350–500 lines of SKILL.md
- Larger than peers (`portfolio-coach` 147 lines, `equity-fundamental-deep-dive` 63 lines, `macro-rates-fx-analysis` 55 lines) because it embeds four dimensions' methodology
- Approach A (inline) was chosen over Approach B (delegating meta-skill) because:
  - Other recipes in this repo all inline methodology — convention match
  - LLM-driven skill flows degrade with chained `load_skill` indirection
  - Coordinating four sub-skill outputs is harder than embedding four short methodology blocks

## Out of scope

- Social sentiment ingestion (Twitter/Reddit) — user explicitly excluded
- Order placement / broker integration — INDMoney MCP is read-only by design
- Backtesting the strategy — user can invoke `backtest` separately if desired
- Real-time intraday signals — `get_market_data` daily bars only

## Implementation handoff

The next step is to write a detailed implementation plan via the
`superpowers:writing-plans` skill. The plan should cover:

1. Create `agent/src/skills/strategy-architect/SKILL.md` with the structure
   above
2. Add `strategy-architect` to `agent/tests/test_recipe_skills_loadable.py`
3. Update `agent/src/skills/portfolio-coach/SKILL.md` routing table with the
   new row pointing to `strategy-architect`
4. Optionally update `docs/mcp-feature-matrix.md` if it tracks recipe skills
