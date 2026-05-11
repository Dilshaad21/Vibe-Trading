# Strategy-Architect Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new recipe skill `strategy-architect` that fuses macroeconomics, news/catalysts, fundamentals, and technicals into multi-horizon trade plans (short/medium/long), adaptive to ticker / portfolio / theme inputs.

**Architecture:** A single `SKILL.md` file under `agent/src/skills/strategy-architect/` containing inline methodology for four analytical dimensions, horizon-weighted signal fusion, trigger overrides, and three output template variants. Methodology is embedded (Approach A in spec) — no chained `load_skill` calls — and uses MCP tools directly (`macro_snapshot`, `get_market_data`, `web_search`, `factor_analysis`, `indmoney_holdings`). The skill plugs into the existing `_RECIPE_SKILLS` test set and is referenced from the `portfolio-coach` routing table.

**Tech Stack:**
- Markdown (SKILL.md is interpreted by the LLM, not executed)
- pytest (validation via `agent/tests/test_recipe_skills_loadable.py`)
- Vibe-Trading SkillsLoader (`agent/src/agent/skills.py`)
- Branch: continues on `spec/strategy-architect-skill` (already created during brainstorming)

**Spec reference:** `docs/superpowers/specs/2026-05-11-strategy-architect-skill-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `agent/src/skills/strategy-architect/SKILL.md` | **Create** | The skill — frontmatter + when-to-use + steps + dimensions + synthesis + templates + failure modes |
| `agent/tests/test_recipe_skills_loadable.py` | **Modify** | Add `"strategy-architect"` to `_RECIPE_SKILLS` set (line 6–11) so it gets covered by all four existing tests |
| `agent/src/skills/portfolio-coach/SKILL.md` | **Modify** | Add one routing-table row pointing comprehensive-analysis questions to `strategy-architect` |

No new Python modules. No new dependencies. The SkillsLoader auto-discovers any directory under `agent/src/skills/` containing a `SKILL.md` with valid frontmatter — no manifest registration needed.

---

## Task 1: Test addition + skeleton SKILL.md (TDD red→green)

**Files:**
- Modify: `agent/tests/test_recipe_skills_loadable.py:6-11`
- Create: `agent/src/skills/strategy-architect/SKILL.md`

- [ ] **Step 1: Add strategy-architect to the _RECIPE_SKILLS set**

Open `agent/tests/test_recipe_skills_loadable.py` and edit the set definition at lines 6-11.

```python
_RECIPE_SKILLS = {
    "macro-rates-fx-analysis",
    "portfolio-rebalance",
    "equity-fundamental-deep-dive",
    "portfolio-coach",
    "strategy-architect",
}
```

- [ ] **Step 2: Run the test — expect failure**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: FAIL on `test_recipe_skills_are_loaded` with `Missing recipe skills: {'strategy-architect'}`

- [ ] **Step 3: Create the skill directory and skeleton SKILL.md**

Create the directory first: `mkdir -p agent/src/skills/strategy-architect`

Then create `agent/src/skills/strategy-architect/SKILL.md` with this minimal valid content (just enough to make the test pass — full content is added in later tasks):

```markdown
---
name: strategy-architect
description: Comprehensive multi-dimensional analysis recipe. Fuses macroeconomics, news/catalysts, fundamentals, and technicals into multi-horizon trade plans (short/medium/long). Adaptive to input — works on a single ticker, a whole portfolio, or a theme. Default entry point for any "should I buy/hold/sell" or "what's my strategy on X" question.
category: recipe
---

# Strategy-architect recipe

## When to use

(filled in by Task 2)
```

- [ ] **Step 4: Run the test — expect pass**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS. The `test_recipe_skills_have_recipe_category` and `test_recipe_load_skill_returns_full_body` tests both check the new skill since it's now in `_RECIPE_SKILLS`.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/test_recipe_skills_loadable.py agent/src/skills/strategy-architect/SKILL.md
git commit -m "$(cat <<'EOF'
feat(skills): scaffold strategy-architect recipe skill

Adds an empty SKILL.md with frontmatter so the skills loader discovers
it, and registers it in the recipe-skills loadable test set. Content
is filled in by subsequent commits per the implementation plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: When-to-use, Inputs, Dispatch logic

**Files:**
- Modify: `agent/src/skills/strategy-architect/SKILL.md`

- [ ] **Step 1: Replace the placeholder body with When-to-use + Inputs + Dispatch**

Open `agent/src/skills/strategy-architect/SKILL.md` and replace everything **after** the closing `---` of the frontmatter with the following content. Keep the frontmatter from Task 1 unchanged.

```markdown
# Strategy-architect recipe

## When to use

- User asks "should I buy / hold / sell [TICKER]?" and wants a complete trade plan (not just fundamentals or just technicals).
- User asks "what's my strategy?" / "how should I position?" / "what should I do next?" and references their portfolio.
- User names a theme or sector ("AI infrastructure", "defense", "weak dollar play") and wants a coherent way to express it.
- The user wants conviction across **all four lenses** — macro, news/catalysts, fundamentals, technicals — fused into one verdict, not chained skill outputs.

For lighter-weight alternatives, point the user to:
- `equity-fundamental-deep-dive` — fundamentals only for one ticker
- `macro-rates-fx-analysis` — macro view only
- `portfolio-coach` — routing + cadence checklist, no trade plan
- `technical-basic` — technicals only

## Inputs

- The user's question (always available).
- Optional: live INDMoney holdings via `indmoney_holdings()` — required for the PORTFOLIO path to produce specific buy/trim/exit recommendations. If unavailable, switch to generic-framework mode and tell the user to run `python scripts/indmoney_oauth.py`.

## Steps

### Step 1: Dispatch — detect input type

The skill produces a different output shape per path. Detect from the user's question and choose one:

| Input pattern | Path | Examples |
|---|---|---|
| Named single ticker | **TICKER** | "analyze NVDA", "should I buy CEG?", "is META a hold?" |
| References "my portfolio" / no ticker / generic positioning question | **PORTFOLIO** | "what's my strategy?", "how should I position now?", "what should I do with my book?" |
| Names a theme, sector, or idea | **THEME** | "AI infrastructure outlook", "is defense a buy?", "play the weak dollar" |

If the input is genuinely ambiguous (e.g. "what about NVDA and AVGO?" — is that a ticker analysis or a theme?), ask **one** clarifying question. Do not guess silently. If still unclear after one clarification, default to TICKER if any ticker was named, else PORTFOLIO.

```

- [ ] **Step 2: Verify the loadable test still passes**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/src/skills/strategy-architect/SKILL.md
git commit -m "$(cat <<'EOF'
feat(strategy-architect): add when-to-use, inputs, dispatch logic

Defines the three dispatch paths (TICKER / PORTFOLIO / THEME), input
expectations, and how to handle ambiguous input.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Four-dimension methodology

**Files:**
- Modify: `agent/src/skills/strategy-architect/SKILL.md`

- [ ] **Step 1: Append the four-dimension data-gathering section**

Append the following content to the end of `agent/src/skills/strategy-architect/SKILL.md` (after the Step 1 dispatch section).

```markdown
### Step 2: Gather all four analytical dimensions

Run **macro first**, then **news + fundamental + technical in parallel**. Never synthesize a strategy from fewer than four dimensions — if one fails, fall back per the failure-modes section but do not silently drop it.

#### Step 2a — Macro (always first)

Call `macro_snapshot()`. Use the response to determine:

- **Rate regime:** cutting / pausing / hiking — affects duration-sensitive growth stocks.
- **Yield curve:** 2s10s sign and slope — recession risk gauge.
- **FX / DXY:** weak USD favors multinationals and EM; strong USD hurts them.
- **Commodity tilts:** elevated oil → energy beneficiaries; high gold → risk-off / inflation tilt.

Map to a single macro **signal** for the asset under analysis:

| Macro condition | Signal for risk assets |
|---|---|
| Cutting + weak USD + steep curve | **Bullish** |
| Pausing + neutral curve + stable USD | **Neutral** |
| Hiking + strong USD + inverted curve | **Bearish** |
| Mixed (e.g. cutting but gold at ATH) | **Neutral** with conflict flag |

Confidence: **High** if all macro fields populated and aligned, **Med** if mixed signals, **Low** if `_errors` is non-empty.

#### Step 2b — News & catalysts (parallel)

Call `web_search()` with these queries (parallel, `max_results=5` each):

For **TICKER** path:
- `"<TICKER> earnings date next quarter"`
- `"<TICKER> analyst rating target price latest"`
- `"<TICKER> news catalyst <current month> <current year>"`
- `"<TICKER> guidance revision"`

For **PORTFOLIO** path:
- `"<TOP_HOLDING_1> earnings date"` (top 3 holdings only)
- `"US economic calendar next 30 days CPI FOMC jobs"`
- `"sector rotation <current month>"`

For **THEME** path:
- `"<THEME> news <current month> <current year>"`
- `"<THEME> regulatory policy update"`
- `"<THEME> ETF flows institutional positioning"`

Synthesize a news **signal**:

- **Bullish** — positive guidance, upgrades, favorable catalysts within horizon
- **Neutral** — no major news, balanced flow
- **Bearish** — negative guidance, downgrades, regulatory headwinds, lawsuits

Confidence: **High** if multiple corroborating sources, **Med** if single source or stale (>30 days), **Low** if 0 results returned (do NOT invent — write "no recent news surfaced").

If a result looks high-value, call `read_url()` for deeper context before deciding.

#### Step 2c — Fundamentals (parallel)

For **TICKER** path, call `web_search()`:
- `"<TICKER> P/E P/B ROE 2026"`
- `"<TICKER> revenue growth EPS latest quarter"`
- `"<TICKER> free cash flow margin"`
- `"<TICKER> sector P/E average"`

If `factor_analysis` is configured for the ticker's market, also call it for quant context.

For **PORTFOLIO** path, work from `indmoney_holdings()` results plus 1–2 `web_search` lookups for aggregate context.

For **THEME** path, look up the representative ETF or 3 leading names:
- `"<TICKER_LIST> valuation comparison"`
- `"<SECTOR_ETF> P/E historical range"`

Synthesize a fundamental **signal**:

- **Bullish** — earnings growth >sector, valuation reasonable (PE within sector range or PEG <1.5), quality metrics solid (ROE >15%, FCF positive)
- **Neutral** — mixed signals
- **Bearish** — slowing growth, valuation stretched (PE >2× sector), deteriorating quality

Confidence: **High** if multiple consistent sources cite real numbers; **Med** if numbers are partial; **Low** if search returns vague/contradictory data. Do NOT invent P/E or growth numbers — if missing, write "n/a" and lower confidence.

#### Step 2d — Technicals (parallel)

For **TICKER** path, call `get_market_data(ticker="<TICKER>", days=90, interval="1d")`. From the OHLCV, compute the technical-basic composite:

- **EMA(12) vs EMA(26):** bullish if EMA(12) > EMA(26), bearish if below
- **RSI(14) Wilder:** overbought >70, oversold <30, neutral 40–60
- **ADX(14):** trend strength — strong if >25, weak if <20
- **OBV slope (10-day):** rising / falling / flat

Compose:

- **Bullish (LONG)** — EMA bullish + RSI not overbought (<70) + OBV rising
- **Bearish (SHORT)** — EMA bearish + RSI not oversold (>30) + OBV falling
- **Neutral** — mixed components, or RSI extreme (>80 or <20 → mean-reversion risk)

Optionally call `pattern_recognition()` for chart-pattern confirmation if the user is asking about timing.

For **PORTFOLIO** path, run the composite on the top-5 holdings + an index proxy (SPY or VOO) to gauge regime.

For **THEME** path, run the composite on the sector ETF (XLK, XLE, XLF, IBB, etc.) most representative of the theme.

Confidence: **High** if ≥30 bars of data AND all 4 sub-indicators are unambiguous; **Med** if mixed sub-indicators; **Low** if <30 bars or `get_market_data` returns insufficient history.
```

- [ ] **Step 2: Verify the loadable test still passes**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/src/skills/strategy-architect/SKILL.md
git commit -m "$(cat <<'EOF'
feat(strategy-architect): add four-dimension data-gathering methodology

Inlines the macro / news / fundamental / technical analysis steps with
specific MCP tool calls, query templates per dispatch path, and
signal+confidence emission rules per dimension.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Synthesis (signal fusion + trigger overrides)

**Files:**
- Modify: `agent/src/skills/strategy-architect/SKILL.md`

- [ ] **Step 1: Append the synthesis section**

Append the following content to the end of `agent/src/skills/strategy-architect/SKILL.md`.

```markdown
### Step 3: Synthesize signals into multi-horizon strategy

Each dimension has returned a **signal** (Bullish / Neutral / Bearish) and **confidence** (High / Med / Low). Combine using **horizon-specific weights**:

| Dimension | Short (1–4w) | Medium (1–6m) | Long (1–3y) |
|---|---|---|---|
| Technical | **40%** | 25% | 15% |
| News / Catalyst | **30%** | 25% | 15% |
| Macro | 20% | 25% | **30%** |
| Fundamental | 10% | 25% | **40%** |

**Composite signal per horizon:** weighted vote. Map signals to numeric values (Bullish = +1, Neutral = 0, Bearish = -1), multiply by horizon weight, sum. Result > +0.3 → Bullish; < -0.3 → Bearish; otherwise Neutral.

**Composite confidence per horizon:**

- All 4 dimensions agree (same signal) → **High**
- 3 of 4 agree → **Medium**
- 2 vs 2 split, or 3+ Neutral → **Low**

**Conflict flag:** if any dimension diverges by >1 step from the composite (e.g. composite Bullish but Fundamental Bearish), surface this explicitly in the output. Tension between dimensions is where insight lives — name it, don't paper over it.

### Step 4: Apply trigger overrides

These hard rules override the synthesized signal regardless of weighted score. Check each before emitting the final trade plan.

| Trigger | Override action |
|---|---|
| RSI > 80 on a position | Trim 25–35% even if composite is Bullish (parabolic) |
| Earnings within 7 days AND composite Bullish | Defer new entries until post-print |
| Position already >12% of book | Cap further additions regardless of signal |
| Stop-loss breached on an existing holding | Exit, do not average down |
| Composite Bearish AND down >25% from cost | Exit, do not hope |
| DOCN-style employer stock concentration >25% of net worth | Mandatory diversification (override any "add" recommendation) |

If a trigger fires, note it in the **Triggers active now** section of the output and adjust the trade plan accordingly.
```

- [ ] **Step 2: Verify the loadable test still passes**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/src/skills/strategy-architect/SKILL.md
git commit -m "$(cat <<'EOF'
feat(strategy-architect): add horizon-weighted synthesis and triggers

Defines the multi-horizon signal-fusion rules (short/medium/long with
different dimension weights), composite-confidence calculation, conflict
flagging, and hard trigger overrides that bypass the weighted score.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Output templates (TICKER, PORTFOLIO, THEME)

**Files:**
- Modify: `agent/src/skills/strategy-architect/SKILL.md`

- [ ] **Step 1: Append the three output templates**

Append the following content to the end of `agent/src/skills/strategy-architect/SKILL.md`.

````markdown
### Step 5: Emit the strategy output

Use the template matching the dispatched path. All three variants share the same top sections (dimensional readout, synthesis, monitoring, sources); the middle section differs.

#### TICKER path output

```markdown
# Strategy: {TICKER} — {one-line headline with composite verdict}

## Dimensional readout
| Dimension | Signal | Confidence | Top evidence |
|---|---|---|---|
| Macro     | …      | …          | rate/FX/commodity bullet |
| News      | …      | …          | earnings date / catalyst / latest rating |
| Fundamental | …    | …          | PE / growth / ROE / FCF |
| Technical | …      | …          | EMA / RSI / ADX / OBV |

## Synthesis
- Composite signal & confidence per horizon (short / medium / long).
- Conflicts/tensions (1-2 lines, only if dimensions diverge).
- Triggers firing right now (if any).

## Trade plan — Short (1–4 weeks)
- **Verdict:** {Buy / Hold / Trim / Sell} ({conviction})
- **Entry trigger:** {price level or signal — e.g. "above $X on close" or "EMA(12) cross"}
- **Position size:** {% of US book, $ amount}
- **Stop-loss:** {price, % below entry}
- **Exit condition:** {target price OR time-based OR signal-based}
- **Top risk:** {single biggest thing that breaks the thesis}

## Trade plan — Medium (1–6 months)
…same six fields…

## Trade plan — Long (1–3 years)
…same six fields, but stop-loss is thesis-based not price-based…

## Monitoring
- **Daily:** 1-2 specific items to watch
- **Weekly:** 1-2 specific items
- **Monthly:** 1-2 specific items
- **Re-run this skill when:** {specific trigger condition}

## Sources
- macro_snapshot fields cited inline above
- web_search URLs (top 3-5)
- get_market_data window: {start_date} → {end_date}
```

#### PORTFOLIO path output

Same top (Dimensional readout, Synthesis) and bottom (Monitoring, Sources) sections. The "Trade plan" sections are replaced by **Book action plan** sections:

```markdown
## Book action plan — Short (1–4 weeks)
- **Top-down stance:** sector tilts (e.g. "+5% to AI infrastructure, -3% to defensives"), cash deployment %, hedge needs.
- **Bottom-up actions:**
  | Ticker | Current weight | Action | Size delta | Reason |
  | … | … | Add / Trim / Exit | … | one-line |
- **Cash deployment phase plan:** if idle cash >10% of book, propose 2-3 tranche schedule.

## Book action plan — Medium (1–6 months)
…same three sections, medium-horizon tuning…

## Book action plan — Long (1–3 years)
…same three sections, long-horizon tuning…
```

#### THEME path output

Same top and bottom sections. The "Trade plan" sections are replaced by **Theme expression plan** sections:

```markdown
## Theme expression plan — Short (1–4 weeks)
- **Thesis:** one-line statement of the bull case for this theme.
- **Counter-thesis:** one-line statement of what would invalidate it.
- **Top names to express the theme (3-5):**
  | Ticker | Why this name | Rationale | Position weight |
  | … | … | … | … |
- **Anti-thesis names (avoid / sell):** tickers that get hurt if the theme plays out, or that have already priced it in.
- **Allocation envelope:** maximum % of book to allocate to this theme on this horizon (e.g. "≤8% of US book").

## Theme expression plan — Medium (1–6 months)
…same five fields…

## Theme expression plan — Long (1–3 years)
…same five fields…
```
````

- [ ] **Step 2: Verify the loadable test still passes**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/src/skills/strategy-architect/SKILL.md
git commit -m "$(cat <<'EOF'
feat(strategy-architect): add three output template variants

TICKER / PORTFOLIO / THEME path output templates with shared top
(dimensional readout, synthesis) and bottom (monitoring, sources)
sections. Middle 'plan' sections differ per path: trade plan for
ticker, book action plan for portfolio, theme expression plan for
theme.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Failure modes & anti-patterns

**Files:**
- Modify: `agent/src/skills/strategy-architect/SKILL.md`

- [ ] **Step 1: Append failure modes and anti-patterns sections**

Append the following content to the end of `agent/src/skills/strategy-architect/SKILL.md`.

```markdown
## Failure modes

| Failure | Behavior |
|---|---|
| `macro_snapshot` returns `_errors` populated | Use the partial fields that succeeded, flag the gap in the dimensional readout, downgrade Macro confidence to Med/Low. Do not block synthesis. |
| `indmoney_holdings` returns `error_kind: needs_auth` (PORTFOLIO path) | Switch to generic-framework mode. Tell the user: "Live portfolio data unavailable — run `python scripts/indmoney_oauth.py` for tailored recommendations." Continue with macro+theme-style guidance. |
| `web_search` returns 0 results for a query | Note "no recent news surfaced" in the dimensional readout; downgrade News confidence to Low. Do NOT invent headlines. |
| `get_market_data` returns fewer than 30 bars | Skip the technical composite. Mark Technical as "insufficient history" with Neutral signal and Low confidence. |
| All four dimensions fail | Refuse to produce a strategy. Output: "Cannot construct a strategy — please retry with a different ticker/portfolio context, or check that the required MCP tools are reachable." |
| Input genuinely ambiguous after one clarifying question | Default to TICKER path if any ticker was named anywhere in the conversation; otherwise default to PORTFOLIO. |

## Anti-patterns (do NOT)

- Do **not** produce a strategy from fewer than four dimensions. If a dimension can't be gathered, say so explicitly in the dimensional readout and reduce composite confidence — never silently drop a dimension.
- Do **not** invent prices, P/E numbers, growth rates, or news headlines. If a value isn't returned by a tool, write "n/a" or "not available" and lower the relevant dimension's confidence.
- Do **not** recommend a position size that violates `portfolio-coach` trigger limits (single position >12%, employer stock >25% of net worth, sector >35%, asset class >65%).
- Do **not** chain to `load_skill` for other skills mid-flow. This skill is inline. If the user wants deeper specialist analysis after, point them to the right skill in the output — don't auto-load.
- Do **not** produce price targets without citing the source (analyst note URL, technical level explanation, or derivation shown in the synthesis).
- Do **not** produce a strategy without all three horizons (short / medium / long) — even if one horizon has Low confidence, emit it with that disclaimer rather than skip it.
```

- [ ] **Step 2: Verify the loadable test still passes**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add agent/src/skills/strategy-architect/SKILL.md
git commit -m "$(cat <<'EOF'
feat(strategy-architect): add failure modes and anti-patterns

Specifies graceful degradation behavior for each MCP tool failure
(macro_snapshot errors, indmoney auth failure, empty web_search,
short market-data window) and explicit DO-NOT list to prevent
hallucinated prices/numbers, skipped dimensions, or trigger-limit
violations.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire into portfolio-coach routing + final verification

**Files:**
- Modify: `agent/src/skills/portfolio-coach/SKILL.md:84` (insert new row before "Default fallback" line)

- [ ] **Step 1: Add a routing-table row in portfolio-coach**

Open `agent/src/skills/portfolio-coach/SKILL.md`. Find the routing table's last row (about Compliance / regulatory-knowledge) at line 84, and insert a new row immediately after it but before the `**Default fallback:**` line on line 86.

The new row, formatted to match the existing pipe table:

```markdown
| Full strategy | "Give me a full strategy on [TICKER / my book / theme]" / "Buy/hold/sell with conviction across all lenses" | `strategy-architect` | Multi-dimensional fused trade plan across macro / news / fundamentals / technicals, multi-horizon |
```

The full edit context — the file should look like this around line 83-87 after the change:

```markdown
| Compliance | "Tax / regulatory rules for [market]?" | `regulatory-knowledge` | A-share / HK / US / crypto rules |
| Full strategy | "Give me a full strategy on [TICKER / my book / theme]" / "Buy/hold/sell with conviction across all lenses" | `strategy-architect` | Multi-dimensional fused trade plan across macro / news / fundamentals / technicals, multi-horizon |

**Default fallback:** if no row matches, route to `portfolio-rebalance` + `risk-analysis`.
```

- [ ] **Step 2: Run the full recipe-loadable test suite**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest agent/tests/test_recipe_skills_loadable.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Run the broader test suite (matches CI)**

Run: `cd /home/dilshaad/trading/Vibe-Trading && pytest --ignore=agent/tests/e2e_backtest --tb=short -q`
Expected: All tests PASS. No regressions from the SKILL.md addition.

- [ ] **Step 4: Run ruff to confirm no Python lint regressions**

Run: `cd /home/dilshaad/trading/Vibe-Trading && ruff check agent`
Expected: clean (no new warnings introduced — the only Python change is the test set addition).

- [ ] **Step 5: Verify the skill is loadable end-to-end via the MCP path**

Run a Python one-liner to confirm the SkillsLoader sees the new skill and its body is non-trivial:

```bash
cd /home/dilshaad/trading/Vibe-Trading && python3 -c "
import sys
sys.path.insert(0, 'agent')
from src.agent.skills import SkillsLoader
loader = SkillsLoader()
skill = next((s for s in loader.skills if s.name == 'strategy-architect'), None)
assert skill is not None, 'strategy-architect not loaded'
assert skill.category == 'recipe', f'wrong category: {skill.category}'
body = loader.get_content('strategy-architect')
assert 'macro_snapshot' in body, 'body missing macro_snapshot reference'
assert 'get_market_data' in body, 'body missing get_market_data reference'
assert 'web_search' in body, 'body missing web_search reference'
assert 'TICKER' in body and 'PORTFOLIO' in body and 'THEME' in body, 'body missing one of the three dispatch paths'
print(f'OK: strategy-architect loaded ({len(body)} chars)')
"
```

Expected: prints `OK: strategy-architect loaded (NNNN chars)` where NNNN is somewhere in the 8,000–15,000 range (roughly 350–500 lines).

- [ ] **Step 6: Commit the portfolio-coach routing change**

```bash
git add agent/src/skills/portfolio-coach/SKILL.md
git commit -m "$(cat <<'EOF'
feat(portfolio-coach): route comprehensive-analysis questions to strategy-architect

Adds a new 'Full strategy' row to the routing table so that questions
like "give me a full strategy on NVDA" or "buy/hold/sell with conviction
across all lenses" surface the new strategy-architect skill rather
than chaining multiple narrower recipes.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Push the branch and surface PR-ready state**

```bash
git push -u origin spec/strategy-architect-skill
```

After push, the branch contains: the design spec (already committed during brainstorming), the skeleton + skill body (Tasks 1–6), and the routing wiring (Task 7). Ready for a PR.

---

## Self-Review

**Spec coverage check (against `docs/superpowers/specs/2026-05-11-strategy-architect-skill-design.md`):**

| Spec section | Implemented in |
|---|---|
| Skill identity / frontmatter | Task 1 Step 3 |
| Dispatch logic (TICKER/PORTFOLIO/THEME) | Task 2 Step 1 |
| Four analytical dimensions (macro/news/fund/tech) | Task 3 Step 1 |
| Sequencing rules (macro first, then parallel) | Task 3 Step 1 (in Step 2 intro) |
| Horizon-weighted synthesis | Task 4 Step 1 |
| Trigger overrides | Task 4 Step 1 |
| Output template — TICKER | Task 5 Step 1 |
| Output template — PORTFOLIO | Task 5 Step 1 |
| Output template — THEME | Task 5 Step 1 |
| Failure modes table | Task 6 Step 1 |
| Anti-patterns DO-NOT list | Task 6 Step 1 |
| `_RECIPE_SKILLS` test addition | Task 1 Step 1 |
| `portfolio-coach` routing table update | Task 7 Step 1 |
| End-to-end loadability verification | Task 7 Step 5 |

All spec sections have a corresponding task. No gaps.

**Placeholder scan:** No "TBD", "TODO", or "implement later" markers. Every code block in the plan contains the actual content the engineer should paste — the markdown snippets are the final SKILL.md content, not pseudocode.

**Type consistency:** No types or signatures involved (markdown only). The MCP tool names (`macro_snapshot`, `get_market_data`, `web_search`, `indmoney_holdings`, `factor_analysis`, `pattern_recognition`, `read_url`) are used consistently across all tasks.

**Cross-task content drift:** The signal/confidence vocabulary (Bullish / Neutral / Bearish + High / Med / Low) is consistent from Task 3 (where dimensions emit them) through Task 4 (where they are fused) through Task 5 (where they appear in templates).
