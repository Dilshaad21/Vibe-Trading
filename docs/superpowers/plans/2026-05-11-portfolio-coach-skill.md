# Portfolio-Coach Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new project skill `portfolio-coach` that routes user portfolio questions to the right specialist skill and provides cadence-based monitoring checklists, then commit and push it to the user's fork.

**Architecture:** A single-file recipe-category skill (`agent/src/skills/portfolio-coach/SKILL.md`) registered in the existing recipe-loader test (`agent/tests/test_recipe_skills_loadable.py`). The skill body is static content — routing table + cadence framework + failure modes — that an LLM applies at invocation time. Optionally calls `indmoney_holdings()` for tailored anchoring.

**Tech Stack:** Markdown (skill body), Python (test), pytest, ruff, git.

**Spec:** `docs/superpowers/specs/2026-05-11-portfolio-coach-skill-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `agent/src/skills/portfolio-coach/SKILL.md` | Create | The skill body — frontmatter + steps + routing table + cadence framework + principles + failure modes |
| `agent/tests/test_recipe_skills_loadable.py` | Modify (line 6-10) | Register `portfolio-coach` in the `_RECIPE_SKILLS` set so the existing recipe-loader assertions cover it |

No new tests are added. The three existing assertions in the test file (`test_recipe_skills_are_loaded`, `test_recipe_skills_have_recipe_category`, `test_recipe_category_in_display_order`) automatically extend to the new skill once it's in the set.

---

## Task 1: Create feature branch

**Files:** none (git only)

- [ ] **Step 1: Verify clean working tree on `main`**

Run:
```bash
git status
git branch --show-current
```

Expected:
```
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
main
```

If the working tree is not clean, stop and surface the issue before proceeding.

- [ ] **Step 2: Create and switch to feature branch**

Run:
```bash
git checkout -b feat/portfolio-coach-skill
```

Expected output: `Switched to a new branch 'feat/portfolio-coach-skill'`

- [ ] **Step 3: Verify on the feature branch**

Run:
```bash
git branch --show-current
```

Expected output: `feat/portfolio-coach-skill`

---

## Task 2: Add `portfolio-coach` to the recipe-skill test set (TDD red phase)

**Files:**
- Modify: `agent/tests/test_recipe_skills_loadable.py:6-10`

- [ ] **Step 1: Edit the test file to register the new skill**

Change lines 6-10 from:
```python
_RECIPE_SKILLS = {
    "macro-rates-fx-analysis",
    "portfolio-rebalance",
    "equity-fundamental-deep-dive",
}
```

To:
```python
_RECIPE_SKILLS = {
    "macro-rates-fx-analysis",
    "portfolio-rebalance",
    "equity-fundamental-deep-dive",
    "portfolio-coach",
}
```

- [ ] **Step 2: Run the recipe-skill tests to confirm they now FAIL**

Run:
```bash
pytest agent/tests/test_recipe_skills_loadable.py -q
```

Expected: 2 tests fail with messages including `Missing recipe skills: {'portfolio-coach'}` and a `KeyError: 'portfolio-coach'` in `test_recipe_skills_have_recipe_category`. The third test (`test_recipe_category_in_display_order`) should still pass since it doesn't reference the new skill. The fourth (`test_recipe_load_skill_returns_full_body`) should also still pass since it's `macro-rates-fx-analysis`-specific.

If all four tests pass at this stage, stop — the SkillsLoader is finding `portfolio-coach` somewhere it shouldn't be (cache, leftover file). Investigate before continuing.

---

## Task 3: Create the `portfolio-coach` skill file

**Files:**
- Create: `agent/src/skills/portfolio-coach/SKILL.md`

- [ ] **Step 1: Create the skill directory and file with full content**

Create the file `agent/src/skills/portfolio-coach/SKILL.md` with this exact content:

````markdown
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
````

- [ ] **Step 2: Verify the file was created**

Run:
```bash
ls agent/src/skills/portfolio-coach/
wc -l agent/src/skills/portfolio-coach/SKILL.md
```

Expected: directory listing shows `SKILL.md`, line count is approximately 100–110 lines.

---

## Task 4: Run tests and verify all pass (TDD green phase)

**Files:** none (verification only)

- [ ] **Step 1: Run the recipe-skill tests**

Run:
```bash
pytest agent/tests/test_recipe_skills_loadable.py -v
```

Expected: all 4 tests pass:
- `test_recipe_skills_are_loaded` — passes (now finds all 4 skills)
- `test_recipe_skills_have_recipe_category` — passes (all 4 have `category: recipe`)
- `test_recipe_category_in_display_order` — passes
- `test_recipe_load_skill_returns_full_body` — passes (still macro-rates-fx-analysis-specific)

If any fail, stop. Most likely failure modes:
- Frontmatter typo (e.g., `category: Recipe` instead of `recipe`) → fix and re-run
- Skill name mismatch in frontmatter vs directory → fix and re-run

- [ ] **Step 2: Run the full skill-system test as a regression check**

Run:
```bash
pytest agent/tests/test_skills.py -q
```

Expected: all tests in `test_skills.py` pass. This catches any case where adding a skill breaks the global `SkillsLoader` (e.g., duplicate name, malformed frontmatter).

- [ ] **Step 3: Verify the skill body loads via `SkillsLoader.get_content`**

Run:
```bash
.venv/bin/python -c "
import sys
sys.path.insert(0, 'agent')
from src.agent.skills import SkillsLoader
loader = SkillsLoader()
body = loader.get_content('portfolio-coach')
assert body, 'Empty body'
assert 'Routing table' in body, 'Missing routing table section'
assert 'Cadence framework' in body, 'Missing cadence section'
assert 'portfolio-rebalance' in body, 'Missing routing reference'
print(f'OK — {len(body.splitlines())} lines, body starts: {body[:80]!r}')
"
```

Expected output ending with `OK — <N> lines, body starts: '---\\nname: portfolio-coach\\n...'`.

If the import fails because `httpx` or another dependency is missing, the project venv at `.venv/` is the canonical environment — fall back to running this in any environment where `pip install -e ".[dev]"` has been run.

---

## Task 5: Lint check

**Files:** none (verification only)

- [ ] **Step 1: Run ruff against the modified test file**

Run:
```bash
ruff check agent/tests/test_recipe_skills_loadable.py agent/src/skills/portfolio-coach/
```

Expected: `All checks passed!` or no output.

The skill body itself is markdown — ruff won't flag it. The test file edit is just adding one line to a set literal, which shouldn't introduce lint issues.

If ruff complains, fix the issue in-place (most likely: trailing whitespace or wrong quote style in the test file edit) and re-run.

---

## Task 6: Commit

**Files:** stages both modified files

- [ ] **Step 1: Verify staged changes match what's expected**

Run:
```bash
git status
```

Expected:
```
On branch feat/portfolio-coach-skill
Changes not staged for commit:
  modified:   agent/tests/test_recipe_skills_loadable.py
Untracked files:
  agent/src/skills/portfolio-coach/
```

- [ ] **Step 2: Stage both files**

Run:
```bash
git add agent/src/skills/portfolio-coach/SKILL.md agent/tests/test_recipe_skills_loadable.py
git status
```

Expected: both files appear under "Changes to be committed". If `agent/src/skills/portfolio-coach/SKILL.md` doesn't appear in the stage, the directory may have been created but the file path is wrong — re-check with `find agent/src/skills/portfolio-coach -type f`.

- [ ] **Step 3: Create the commit**

Run:
```bash
git commit -m "$(cat <<'EOF'
feat(skills): add portfolio-coach decision-framework skill

Routes user portfolio questions to the right specialist skill
(portfolio-rebalance, risk-analysis, hedging-strategy, etc.) and
provides daily/weekly/monthly/quarterly watch lists tuned for
max-profit + stability. Optionally anchors guidance to live
INDMoney holdings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds with output like `[feat/portfolio-coach-skill abc1234] feat(skills): add portfolio-coach decision-framework skill`.

If a pre-commit hook fails, do NOT use `--amend` or `--no-verify`. Read the hook output, fix the issue, re-stage, and create a new commit.

- [ ] **Step 4: Verify the commit landed**

Run:
```bash
git log --oneline -1
git show --stat HEAD
```

Expected:
- Latest commit is the one just created.
- `git show --stat HEAD` shows 2 files changed: `agent/src/skills/portfolio-coach/SKILL.md` (new file, ~100 insertions) and `agent/tests/test_recipe_skills_loadable.py` (1 insertion).

---

## Task 7: Push to fork

**Files:** none (git push only)

- [ ] **Step 1: Confirm the remote `origin` points to the user's fork**

Run:
```bash
git remote -v | grep origin
```

Expected: `origin\tgit@github.com:Dilshaad21/Vibe-Trading.git (fetch)` and `(push)`.

If `origin` points to the upstream (`HKUDS/Vibe-Trading`), STOP — do not push. Surface the issue.

- [ ] **Step 2: Push the feature branch with upstream tracking**

Run:
```bash
git push -u origin feat/portfolio-coach-skill
```

Expected: output ends with `* [new branch]      feat/portfolio-coach-skill -> feat/portfolio-coach-skill` and `Branch 'feat/portfolio-coach-skill' set up to track remote branch 'feat/portfolio-coach-skill' from 'origin'.`

If the push is rejected (e.g., auth issue), surface the error to the user — do NOT use `--force`.

- [ ] **Step 3: Verify the push**

Run:
```bash
git log origin/feat/portfolio-coach-skill --oneline -1
```

Expected: shows the commit just pushed, identical SHA to local `HEAD`.

---

## Task 8: Final sanity check and report

**Files:** none

- [ ] **Step 1: Print a summary of what was added**

Run:
```bash
git log main..feat/portfolio-coach-skill --oneline
echo "---"
git diff main..feat/portfolio-coach-skill --stat
```

Expected:
- One commit shown: `feat(skills): add portfolio-coach decision-framework skill`.
- Diff stat: 2 files changed, ~101 insertions(+), 0 deletions(-).

- [ ] **Step 2: Confirm everything is in place**

Final state should be:
- New file `agent/src/skills/portfolio-coach/SKILL.md` exists and loads via `SkillsLoader`.
- `agent/tests/test_recipe_skills_loadable.py` has `portfolio-coach` in `_RECIPE_SKILLS`.
- `pytest agent/tests/test_recipe_skills_loadable.py` and `pytest agent/tests/test_skills.py` both pass.
- `ruff check` passes on changed files.
- Single commit on `feat/portfolio-coach-skill`, pushed to `origin`.
- No PR opened (per spec — offer it as a follow-up).

- [ ] **Step 3: Offer next steps to the user**

Surface to the user:
- The branch is pushed; the user can open a PR via `gh pr create` or the GitHub web UI.
- Mention that this skill takes effect for any new MCP session that reloads `SkillsLoader`. Existing sessions need to restart `vibe-trading-mcp` to see it.

---

## Self-review notes

Spec coverage:
- Skill identity (frontmatter, file path) — Task 3 ✓
- Skill body structure (8 top-level sections) — Task 3 ✓
- Routing table (24 rows, ~30 unique skills) — Task 3 ✓
- Cadence framework (4 tiers + trigger overrides) — Task 3 ✓
- Profit-vs-stability principles (3 rules) — Task 3 ✓
- Failure modes (3 modes) — Task 3 ✓
- Testing (single edit) — Tasks 2, 4 ✓
- Verification (pytest + ruff + get_content) — Tasks 4, 5 ✓
- Commit & push protocol (branch, message, push to origin only) — Tasks 1, 6, 7 ✓
- PR not opened automatically — Task 8 surfaces follow-up ✓

Placeholder scan: no TBDs, no "implement appropriate handling", every code/command step has the literal content.

Type / name consistency: `portfolio-coach` used identically across all tasks. The frontmatter `category: recipe` matches the test's expectation in `test_recipe_skills_have_recipe_category`. The test set `_RECIPE_SKILLS` is the only Python identifier referenced.

No gaps detected.
