# MCP / LLM boundary — design

**Status:** Draft
**Date:** 2026-05-09
**Author:** dmuthalif (with Claude Code, brainstorming skill)

## 1. Problem & goal

When the user invokes Vibe-Trading via `vibe-trading-mcp` from a Claude Code
session, most tools work fine — the MCP client is the LLM, the MCP server is
just a tool process. The exception is `run_swarm`: swarm workers in
`agent/src/swarm/worker.py:225` hardwire `ChatLLM(model_name=...)`, which
calls `build_llm()` → reads `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY` env
vars at process startup. Without those env vars, every swarm preset crashes
with "0 tokens processed".

The user's MCP-only setup (Claude Code as the orchestrating LLM, no separate
API key) hits this gap every time analysis routes through a swarm preset.
The current ad-hoc workaround — agent says "I'll build the macro analysis
directly using web search" — is a band-aid that gets re-invented per session.

**Goal:** A permanent solution that:
1. Keeps Claude Code as the only LLM — no second API key.
2. Replaces the most-used swarm presets with **deterministic data tools +
   recipe skills** that Claude Code orchestrates itself.
3. Documents the boundary clearly so future sessions don't try `run_swarm`
   first and fall back ad hoc.
4. Honestly flags the small set of presets that genuinely need
   adversarial multi-voice debate (those stay swarm-only, opt-in).

**Out of scope for this PR:**
- Replacing all 24 data-heavy swarm presets in one shot. Start with three
  (macro, portfolio rebalance, equity fundamentals); add more as user demand
  surfaces.
- Replacing the 5 genuinely adversarial presets (`investment_committee`,
  `geopolitical_war_room`, `event_driven_task_force`, `sentiment_intelligence_team`,
  `social_alpha_team`). Those need real multi-voice debate; we document them
  as opt-in swarm-only and stop trying to run them via MCP.
- A general-purpose "MCP sampling" route where the server asks the client to
  call its own LLM. The MCP 2025 spec supports this, but the FastMCP / Claude
  Code support story is uneven; revisit later if the recipe approach
  underdelivers.

## 2. Approach

Three layers, each independently testable and shippable:

### Layer 1 — Data tools (new MCP tools, deterministic)

Add MCP tools that fill the data gaps swarm workers used to fetch via LLM
plus tool calls. The first tool, scoped to this PR:

- **`macro_snapshot`** — pulls central-bank policy rates (Fed, RBI, ECB,
  BoE, BoJ), key sovereign yields (US 2Y/10Y/30Y, India G-sec 10Y), USD/INR
  + DXY, commodity benchmarks (Brent/WTI, gold). Returns structured JSON.
  Sources: `yfinance` (already a project dep) for FX + commodities + UST,
  `akshare` (already a project dep) for India G-sec, FRED public CSV
  endpoints for Fed/ECB rates (no API key — FRED CSV download is open).
  Cached locally under `agent/uploads/macro/<asof>.json` with a 1-hour TTL,
  same SnapshotCache pattern as INDMoney.

Future PRs add more tools (`sector_indices_quote`, `earnings_calendar`,
`yield_curve_history`, etc.) as needed. We don't speculate.

### Layer 2 — Recipe skills (new SKILL.md files)

Each recipe is a markdown file at `agent/src/skills/<skill-name>/SKILL.md`
(flat layout — the project's `SkillsLoader` walks immediate children of
`agent/src/skills/` looking for `SKILL.md` directly; categories come from
the frontmatter, not the path). An MCP-client agent (Claude Code) loads a
recipe via `load_skill(name="<skill-name>")` and follows it step-by-step.
The body is a sequence of MCP tool calls + Claude-Code-side synthesis
prompts — it replaces the swarm preset's worker pipeline with single-LLM
orchestration.

First batch in this PR:

| Recipe skill (directory + frontmatter `name`) | Replaces preset | Inputs | Output expected |
|---|---|---|---|
| `macro-rates-fx-analysis` | `macro_rates_fx_desk` | (none — reads current macro state) | Macro backdrop synthesis: rate trajectories, FX positioning, commodity signals, asset-allocation implications |
| `portfolio-rebalance` | `portfolio_review_board` | INDMoney holdings (auto-fetched via `indmoney_holdings`), optional target allocation | Performance attribution, concentration flags, rebalance recommendation |
| `equity-fundamental-deep-dive` | `fundamental_research_team` (one ticker at a time) | Ticker symbol | Financial-health, valuation, quality assessment + buy/hold/sell |

Each SKILL.md frontmatter sets `category: recipe` so the three new skills
cluster together in `list_skills()` output. To make the new "recipe"
category render before "other" in the agent's grouped display, add
`"recipe"` to `SkillsLoader._CATEGORY_ORDER` in `agent/src/agent/skills.py`
(one-line change).

### Layer 3 — Documentation

A new section in `CLAUDE.md` (and a small companion doc at
`docs/mcp-feature-matrix.md`) documenting:

- Which tools work via MCP without LLM creds (most of them — we'll list).
- Which tool genuinely needs LLM creds (`run_swarm`).
- For tasks that historically used a swarm preset: prefer the corresponding
  recipe skill if one exists; fall back to swarm only if you've explicitly
  opted in by setting `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY`.
- The five genuinely-adversarial presets that swarms still own, with a
  note that they're worth the env-var setup if you want them.

## 3. Architecture

```
agent/src/integrations/macro/                ← new module (mirrors integrations/indmoney/)
├── __init__.py
├── snapshot.py                              ← fetch + normalize
├── cache.py                                 ← reuses SnapshotCache pattern
└── README.md

agent/src/tools/
└── macro_snapshot_tool.py                   ← BaseTool subclass

agent/mcp_server.py                          ← +1 @mcp.tool wrapper for macro_snapshot
                                                (tool count goes from 24 → 25)

agent/src/skills/                            ← flat: existing 74 skills + 3 new recipe skills, all siblings
├── macro-rates-fx-analysis/
│   └── SKILL.md                             ← frontmatter category: recipe
├── portfolio-rebalance/
│   └── SKILL.md                             ← frontmatter category: recipe
└── equity-fundamental-deep-dive/
    └── SKILL.md                             ← frontmatter category: recipe

agent/src/agent/skills.py                    ← +"recipe" to _CATEGORY_ORDER tuple

agent/tests/
├── test_macro_snapshot.py                   ← unit tests, no network
├── test_macro_snapshot_tool_contract.py     ← end-to-end with httpx.MockTransport
└── test_recipe_skills_loadable.py           ← assert list_skills() includes the 3 new names

CLAUDE.md                                    ← + section "MCP / LLM boundary"
docs/mcp-feature-matrix.md                   ← + new doc
```

Dependency isolation: only `snapshot.py` imports `yfinance` / `akshare` /
`httpx`. The cache + tool wrapper are pure stdlib + pandas.

## 4. Data model — `macro_snapshot` output

```jsonc
{
  "asof": "2026-05-09T14:30:00+05:30",
  "central_bank_rates": {
    "fed_funds_target_upper": 5.50,
    "fed_funds_target_lower": 5.25,
    "rbi_repo": 6.50,
    "ecb_deposit": 4.00,
    "boe_bank_rate": 5.25,
    "boj_policy": -0.10
  },
  "yields": {
    "ust_2y": 4.81, "ust_10y": 4.34, "ust_30y": 4.52,
    "india_gsec_10y": 7.12,
    "us_2s10s_bp": -47                       // pre-computed spread
  },
  "fx": {
    "usd_inr": 83.45, "dxy": 104.21,
    "eur_usd": 1.08,  "usd_jpy": 152.30
  },
  "commodities": {
    "brent_usd": 84.20, "wti_usd": 80.05,
    "gold_usd_oz": 2310.50
  },
  "_sources": {                              // provenance, helps with debugging
    "fed_funds_target_upper": "FRED:DFEDTARU",
    "ust_10y":                "yfinance:^TNX",
    "...": "..."
  },
  "_cache_age_seconds": 0                    // 0 on fresh fetch, >0 on cache hit
}
```

Failure mode: if any single source fails (FRED 503, yfinance returns NaN,
network timeout), the corresponding field is set to `null` and an entry is
added to a top-level `_errors` array. The tool never raises — it returns
a partial snapshot with provenance, so Claude Code can decide what to do
with the gaps.

## 5. Recipe skill format

Each recipe is a SKILL.md with the project's existing frontmatter shape:

```markdown
---
name: macro-rates-fx-analysis
description: Synthesise a cross-asset macro view (rates, FX, commodities)
  from current data. Replaces the macro_rates_fx_desk swarm preset for
  single-LLM (e.g. Claude Code via MCP) orchestration.
category: recipe
---

# Macro / Rates / FX analysis recipe

## When to use
- User asks for macro backdrop, rate trajectory, FX positioning, or
  asset-allocation implications of current macro conditions.
- The `macro_rates_fx_desk` swarm preset would be the alternative if an
  LLM provider were configured.

## Inputs
None — operates on current global macro state.

## Steps

### 1. Pull current data
Call MCP tool `macro_snapshot()`. Surface any non-null `_errors` to the
user before continuing.

### 2. Pull recent central-bank communications
Call MCP tool `web_search` for, in parallel:
- "Fed rate decision <CURRENT_MONTH> <CURRENT_YEAR>"
- "RBI MPC <CURRENT_MONTH> <CURRENT_YEAR>"
- "ECB rate <CURRENT_MONTH> <CURRENT_YEAR>"
Cap at 5 results each. Skim for actual policy moves vs commentary.

### 3. Synthesise (Claude Code's own reasoning)
Produce a short report covering:
- **Rate trajectory:** where each major CB sits, market-implied path,
  divergence signals (e.g. Fed cutting while RBI holds → INR strength).
- **Yield curve dynamics:** US 2s10s, India 10Y level, what the curve
  is pricing.
- **FX positioning:** USD strength via DXY, USD/INR direction, key
  cross-asset implications.
- **Commodity signals:** oil/gold as inflation/risk proxies.
- **Asset-allocation implications:** what this combination favours or
  argues against, scoped to the user's known portfolio shape if
  available (call `indmoney_holdings` first if in doubt).

## Output format
Markdown report. Lead with a one-sentence "macro stance" (e.g.
"Cautiously risk-on with USD-strength tailwinds"). Then sections per
above. Cite the data sources from `_sources` so the user can audit.

## Failure modes
If `macro_snapshot` returns mostly nulls, do NOT synthesise — surface
the data-quality problem and stop.
```

The other two recipes follow the same shape with their own steps.

## 6. Documentation: the boundary

Add to `CLAUDE.md` after the existing "Skill namespaces" section:

```markdown
### MCP / LLM boundary (when does a tool need a separate LLM?)

Most `vibe-trading-mcp` tools are pure compute or data-fetch and work
with no LLM provider configured — Claude Code (the MCP client) is the
only LLM in the loop. The exception is `run_swarm`, whose workers
spawn their own `ChatLLM` (`agent/src/swarm/worker.py:225`) and call
out to `<PROVIDER>_API_KEY` env vars at runtime.

| Tool / preset family | Needs LLM creds? | How to invoke from Claude Code |
|---|---|---|
| Data + math tools (`macro_snapshot`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `backtest`, `analyze_trade_journal`, `indmoney_holdings`, etc.) | No | Direct MCP tool call |
| Recipe skills (skills with `category: recipe` in their SKILL.md frontmatter) | No | `load_skill(name="<recipe-name>")`, then follow steps |
| Data-heavy swarm presets (`macro_rates_fx_desk`, `portfolio_review_board`, `fundamental_research_team`, etc.) | Yes (workers each call ChatLLM) | **Prefer the corresponding recipe skill if one exists.** Fall back to `run_swarm` only if you've set `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY`. |
| Adversarial / multi-voice presets (`investment_committee`, `geopolitical_war_room`, `event_driven_task_force`, `sentiment_intelligence_team`, `social_alpha_team`) | Yes | These genuinely need multi-voice debate; recipes can't replicate them. Set the env vars to opt in. |

Recipe skills are the canonical replacement for data-heavy swarm presets
when running via MCP. See `docs/mcp-feature-matrix.md` for the full
preset → recipe mapping (filled in over time as recipes are added).
```

Companion doc `docs/mcp-feature-matrix.md` lists every preset and its
status: replaced-by-recipe, swarm-only, or pending.

## 7. Testing

| Test file | What it verifies |
|---|---|
| `test_macro_snapshot.py` | Pure-data normalize functions: FRED CSV parsing, yfinance ticker → dict, partial-failure handling (one source down → other fields populated, `_errors` populated). No network. |
| `test_macro_snapshot_tool_contract.py` | End-to-end `MacroSnapshotTool().execute()` via `httpx.MockTransport` (same pattern as INDMoney contract tests). Asserts cache hit/miss, error envelope. |
| `test_recipe_skills_loadable.py` | `list_skills()` returns names containing all three recipes. `load_skill(name="macro-rates-fx-analysis")` returns content with the expected frontmatter. |
| `test_indmoney_registry.py` (existing) | Verify the FastMCP tool surface still has the new `macro_snapshot` and the existing 24 stay registered. Update count assertion 24 → 25. |

## 8. Rollout / scope

Single PR, ~6 commits TDD-style:

1. `feat(macro): macro_snapshot data fetcher + cache + tool wrapper`
2. `feat(mcp): expose macro_snapshot via @mcp.tool`
3. `feat(skills): add macro-rates-fx-analysis recipe`
4. `feat(skills): add portfolio-rebalance recipe`
5. `feat(skills): add equity-fundamental-deep-dive recipe`
6. `docs: MCP / LLM boundary in CLAUDE.md + feature matrix`

After merge, the user can verify by running, in any Claude Code session
connected to `vibe-trading-mcp`:

```
load_skill(name="macro-rates-fx-analysis")
```

Claude Code reads the recipe, calls `macro_snapshot()`, calls
`web_search()`, and synthesises — all with one LLM (itself), no second
API key, no swarm crash.

## 9. Open questions / risks

1. **FRED CSV download URL stability.** Public, no API key, but if FRED
   throttles or changes URL formats we're brittle. Mitigation: the partial-
   failure design — one source down doesn't break the snapshot. Consider
   the `fredapi` package as a follow-up if hits get noisy.

2. **akshare for India G-sec.** akshare is already a project dep but its
   India endpoints are less stable than its A-share ones. If unavailable,
   field returns `null` with `_errors` entry. Acceptable.

3. **Recipe drift.** If we change underlying tool signatures, recipes
   silently break. Mitigation: recipe-loadability test (Task #7 above) +
   a follow-up "recipe contract test" that calls each recipe's tools with
   stub responses to verify the steps still flow.

4. **Discoverability.** Will an MCP-client agent know to prefer
   `load_skill(recipe/...)` over `run_swarm` for these cases? Mitigation:
   the boundary table in CLAUDE.md (section 6 above), plus tagging
   each new SKILL.md with `category: recipe` so they cluster together in
   `list_skills()` output.

5. **The five adversarial presets.** Document them as opt-in. If users
   complain about the gap, revisit MCP sampling (server-asks-client) as
   a v2 path; out of scope for this PR.
