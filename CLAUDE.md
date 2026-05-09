# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

Vibe-Trading (`vibe-trading-ai` on PyPI) is a Python 3.11+ multi-agent finance research / backtesting toolkit with three runtime entry points and a React frontend:

- `vibe-trading` — interactive CLI/TUI (`agent/cli.py`)
- `vibe-trading serve` — FastAPI server (`agent/api_server.py`) that also serves the built frontend from `frontend/dist`
- `vibe-trading-mcp` — FastMCP stdio/SSE server exposing 22 tools (`agent/mcp_server.py`)

The package layout is non-standard: `pyproject.toml` sets `package-dir = {"" = "agent"}`, so `cli`, `api_server`, `mcp_server` are top-level modules and the rest lives under `src.*` and `backtest.*` (both rooted at `agent/`). Tests, scripts, and any new code that imports project modules must keep `agent/` on `sys.path` (see `agent/tests/conftest.py`).

## Common commands

```bash
# Install (editable, with dev extras)
pip install -e ".[dev]"

# Tests — always exclude the e2e_backtest dir (matches CI)
pytest --ignore=agent/tests/e2e_backtest --tb=short -q

# Single test file / single test
pytest agent/tests/test_correlation.py -q
pytest agent/tests/test_correlation.py::test_name -q

# Lint (ruff is configured in pyproject; rules: E, F, W; line-length=120; E501 ignored)
ruff check agent

# Run servers manually
vibe-trading serve --port 8899          # backend
cd frontend && npm install && npm run dev  # frontend dev server on :5899, proxies to :8899
cd frontend && npm run build               # tsc -b && vite build

# Or use the orchestrator script (manages PIDs/logs under .vibe-dev/)
scripts/dev up | stop | restart [backend|frontend|all] | status | logs [service] | urls

# Docker
docker compose up --build   # exposes 127.0.0.1:8899 by default, runs as non-root

# INDMoney portfolio integration (one-time OAuth dance — Authorization Code + PKCE
# + Dynamic Client Registration; saves tokens to ~/.vibe-trading/indmoney/)
python scripts/indmoney_oauth.py

# Expose vibe-trading-mcp to a Claude Code session (per-machine, gitignored —
# run once after `pip install -e ".[dev]"` in any new environment, e.g. on a
# fresh machine, in a new venv, or after a clone). Claude Code becomes the
# orchestrating LLM and gets every registered Vibe-Trading tool — backtest,
# factor_analysis, indmoney_holdings, indmoney_sync, list_skills, load_skill,
# etc. — callable directly. No separate LLM API key needed; your Claude Code
# subscription covers it.
claude mcp add vibe-trading $(which vibe-trading-mcp)
# After registering, restart your Claude Code session in this directory and:
#   `claude mcp list`  → terminal: vibe-trading appears in the registry
#   `/mcp`             → inside Claude Code: vibe-trading shows as connected
# Other MCP clients (Cursor, Claude Desktop, OpenClaw) follow the same pattern;
# see the docstring at the top of agent/mcp_server.py for client-specific config.
```

CI (`.github/workflows/test.yml`) runs: `pip install -e ".[dev]"`, `py_compile` on the entry-point and core files, `pytest` (same ignore as above), then `npm ci && npm run build` in `frontend/`. Match this locally before pushing.

## Architecture

### Agent loop (`agent/src/agent/`)
ReAct-style core in `loop.py` with **five-layer context management** — when changing prompt/context behavior, understand which layer applies before patching:

1. **microcompact** — silently prunes old tool results each iteration
2. **context_collapse** — folds long text blocks without an LLM call
3. **auto_compact** — LLM structured summary with token-budget tail protection (`TOKEN_THRESHOLD`, default 40000)
4. **compact tool** — model explicitly invokes the compact tool to trigger layer 3
5. **iterative update** — Nth compression updates the previous summary instead of starting fresh

Read/write tool batching: consecutive read-only tools execute in parallel via threads. Skills use **progressive disclosure** — only one-line descriptions land in the system prompt; full `SKILL.md` bodies are loaded on demand by the `load_skill` tool (`agent/src/agent/skills.py`).

### Modules (under `agent/src/`)
- `agent/` — ReAct loop, context builder, workspace memory, tool registry, trace writer
- `core/` — run state store + subprocess runner that executes generated backtest code and collects artifacts (`equity.csv`, `metrics.csv`, trade log) per the spec in `core/runner.py`
- `providers/` — LLM provider abstraction. Supported providers and metadata live in `providers/llm_providers.json`; OAuth flow for OpenAI Codex in `providers/openai_codex.py`
- `session/` — session store + FTS5 search; SSE event streaming
- `swarm/` — DAG orchestration. `presets/*.yaml` defines 29 multi-agent teams; `runtime.py` schedules workers by topological layer (parallel within layer, serial between layers) on a background daemon thread
- `tools/` — agent tools wired into the registry (also surfaced as MCP tools); `path_utils.py` enforces sandbox roots
- `integrations/indmoney/` — read-only MCP **client** of `mcp.indmoney.com/mcp` for live portfolio (holdings, totals, sector/asset-class breakdowns). Powers the `indmoney_holdings` and `indmoney_sync` agent tools. See [`docs/indmoney.md`](docs/indmoney.md) before changing anything here — most design choices are reactions to upstream surprises
- `skills/<category>/<skill>/SKILL.md` — 74 **project skills** in 8 categories (`data-source`, `strategy`, `analysis`, `asset-class`, `crypto`, `flow`, `tool`, plus risk). Loaded via the MCP tools `list_skills` / `load_skill` — NOT via Claude Code's built-in `Skill(...)` tool, which loads a different (plugin/superpower) skill registry. See "Skill namespaces" below if you're an agent connected to `vibe-trading-mcp`
- `shadow_account/` — Jinja2 templates for the shadow-account HTML/PDF reports
- `memory/` — persistent cross-session memory backing the `remember` tool

### Backtest (`agent/backtest/`)
- `engines/` — 7 market engines (`china_a`, `china_futures`, `crypto`, `forex`, `global_equity`, `global_futures`, `options_portfolio`) all extending `base.BaseEngine`; plus `composite.py` for cross-market portfolios with a shared capital pool
- `loaders/` — data sources (`tushare`, `tushare_fundamentals`, `yfinance_loader`, `akshare_loader`, `okx`, `ccxt_loader`, `futu`) implementing the `base.DataLoader` Protocol; selection via `registry.py` with auto-fallback
- `optimizers/` — `mean_variance`, `risk_parity`, `equal_volatility`, `max_diversification` (extend `base.BaseOptimizer`)
- `runner.py` — runs generated strategy code in a subprocess and validates artifacts against `_ARTIFACTS_SPEC`
- `validation.py` — invoked via `python -m backtest.validation <run_dir>`; validates required CSVs/JSON

### Frontend (`frontend/`)
React 19 + TypeScript + Vite 6 + Tailwind. Routing in `src/router.tsx` uses **route-level lazy loading** (initial bundle ~262KB after the 688KB→262KB shrink — preserve this when adding pages). State via Zustand (`src/stores/`). Charts via ECharts. UI text is English; LLM output follows the user's language.

### Sandbox & security boundaries
Several tools enforce path containment / sandbox roots — when adding or editing tools that touch the filesystem or shell, verify against the existing security tests:

- `agent/tests/test_path_safety.py`, `test_doc_reader_security.py`, `test_web_reader_security.py`, `test_file_tool_sandbox_security.py`, `test_shadow_codegen_security.py`, `test_tool_registry_security.py`, `test_security_auth_api.py`, `test_upload_security.py`, `test_backtest_runner_security.py`
- File/journal readers default to `agent/uploads`, `agent/runs`, `./uploads`, `./data`, `~/.vibe-trading/uploads`, `~/.vibe-trading/imports`; extra roots via `VIBE_TRADING_ALLOWED_FILE_ROOTS` / `VIBE_TRADING_ALLOWED_RUN_ROOTS`
- Shell-capable tools are gated to the local CLI by default; remote API/MCP-SSE deployments must opt in with `VIBE_TRADING_ENABLE_SHELL_TOOLS=1`
- `API_AUTH_KEY` is required for any non-loopback caller of the API server (and gated settings reads/writes)
- Localhost dev workflows are intentionally low-friction — do not regress that ergonomics when tightening remote paths

### Skill namespaces (project skills vs. Claude Code's `Skill` tool)

Two unrelated systems both call themselves "skills" and they are easy to confuse — especially for an MCP client (Claude Code, Cursor, Claude Desktop) connected to `vibe-trading-mcp`. They live in separate registries:

| System | Where it lives | How an agent invokes it |
|---|---|---|
| **Project skills** (this repo) | `agent/src/skills/<category>/<skill>/SKILL.md` — 74 finance/analysis playbooks (`fundamental-filter`, `risk-analysis`, `strategy-generate`, etc.) | MCP tool calls `list_skills()` and `load_skill(name="<skill>")` exposed by `agent/mcp_server.py` |
| **Plugin/superpower skills** | Claude Code's installed plugins (`brainstorming`, `executing-plans`, `writing-plans`, etc.) | Claude Code's built-in `Skill(skill="<skill>")` tool |

Common failure mode: an agent sees "load `fundamental-filter`" in context and reflexively calls `Skill(skill="fundamental-filter")`. That bounces with `Unknown skill: fundamental-filter` because it checked the plugin registry, not this project's skills. The fix is always `load_skill(name="fundamental-filter")` (the MCP tool), not `Skill(...)`.

If you are an MCP-client agent and need a project skill: call `list_skills()` first to discover names, then `load_skill(name=...)` to pull the SKILL.md content. The SKILL.md will reference other MCP tools (`factor_analysis`, `web_search`, `backtest`, etc.) — call those directly the same way.

### MCP / LLM boundary (when does a tool need a separate LLM?)

Most `vibe-trading-mcp` tools are pure compute or data-fetch and work with no LLM provider configured — Claude Code (the MCP client) is the only LLM in the loop. The exception is `run_swarm`, whose workers spawn their own `ChatLLM` (`agent/src/swarm/worker.py:225`) and require `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY` env vars to function.

| Tool / preset family | Needs LLM creds? | How to invoke from Claude Code |
|---|---|---|
| Data + math tools (`macro_snapshot`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `backtest`, `analyze_trade_journal`, `indmoney_holdings`, `indmoney_sync`, etc.) | No | Direct MCP tool call |
| Recipe skills (skills with `category: recipe` in their SKILL.md frontmatter) | No | `load_skill(name="<recipe-name>")`, then follow steps |
| Data-heavy swarm presets (`macro_rates_fx_desk`, `portfolio_review_board`, `fundamental_research_team`, etc.) | Yes (workers each call ChatLLM) | **Prefer the corresponding recipe skill if one exists.** Fall back to `run_swarm` only after setting `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY`. |
| Adversarial / multi-voice presets (`investment_committee`, `geopolitical_war_room`, `event_driven_task_force`, `sentiment_intelligence_team`, `social_alpha_team`) | Yes | These genuinely need multi-voice debate; recipes can't replicate them. Set the env vars to opt in. |

Recipe skills are the canonical replacement for data-heavy swarm presets when running via MCP. See [`docs/mcp-feature-matrix.md`](docs/mcp-feature-matrix.md) for the full preset → recipe mapping (filled in over time as recipes are added).

## Project conventions

From `CONTRIBUTING.md` (these are project-specific, not generic):

- Files: aim < 400 lines, hard cap 800
- Python: Google-style docstrings, type hints encouraged
- Config via `.env` / YAML / constants — no hardcoding
- Delete unused code rather than commenting it out
- OKX symbol format is `BASE-QUOTE` uppercase (e.g. `BTC-USDT`)
- UI text in English; LLM output language follows the user
- Conventional Commits for messages (`feat:`, `fix:`, `docs:`, `test:` …)

## Protected modules — ask before modifying

Per `CONTRIBUTING.md`, treat these as core and open an issue / ask before non-trivial changes:

- `agent/src/agent/` (ReAct loop, context, skills loader)
- `agent/src/session/`
- `agent/src/providers/`

`agent/src/skills/`, `agent/src/tools/`, `agent/backtest/`, `agent/src/swarm/presets/`, and `frontend/` are open for direct contributions.

## Adding a new skill, preset, or loader

- **Skill**: create `agent/src/skills/<category>/<skill-name>/SKILL.md` with frontmatter (name/description/category). Optional supporting files (`examples.md`, etc.) are loaded on demand by `Skill.load_support_file`. Add a regression test under `agent/tests/`.
- **Swarm preset**: add a YAML to `agent/src/swarm/presets/` defining agents and the DAG. The presets are bundled as package data — `pyproject.toml`'s `[tool.setuptools.package-data]` already includes them; do not move the directory without updating that section (see prior PyPI bundling regression in README news for 2026-04-28).
- **Data loader**: implement `backtest/loaders/base.DataLoader`, register in `backtest/loaders/registry.py`, add tests.

## Portfolio analysis & rebalancing workflow

Use plain English prompts — the agent picks the right skill, data source, and backtest engine automatically.

### 1. Start the agent
```bash
vibe-trading                    # interactive TUI
vibe-trading serve --port 8899  # Web UI at localhost:8899
```

### 2. Upload your portfolio / trade history
```bash
vibe-trading --upload my_trades.csv  # broker export (同花顺/东财/富途/generic CSV)
```
Then: *"Profile my current portfolio and identify concentration risks"*

### 3. Analysis prompts
- **Allocation:** *"Analyze my portfolio allocation across sectors and asset classes, identify overweights"*
- **Correlation:** *"Show a correlation heatmap for my holdings and flag highly correlated positions"*
- **Risk metrics:** *"Calculate VaR, max drawdown, and Sharpe ratio for my current portfolio"*

### 4. Market trend analysis
- *"Run macro analysis — current Fed rate path, sector rotation signals, and EM vs DM outlook"*
- Full screening → backtest → risk audit pipeline via swarm:
  ```bash
  vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'
  ```

### 5. Rebalancing recommendations
- *"Given my current holdings, suggest a rebalance to target 60/40 equity/bond with max 10% single-stock weight"*
- *"Run mean-variance optimization on my portfolio with max 15% drawdown constraint"*
- The 4 built-in optimizers (`mean_variance`, `risk_parity`, `equal_volatility`, `max_diversification`) are invoked automatically when you ask for optimization.

### 6. Backtest a rebalancing strategy before acting
```bash
vibe-trading run -p "Backtest monthly rebalancing of [your tickers] back to equal weight over 2 years"
```

### 7. Get a committee view before making a call
```bash
vibe-trading --swarm-run investment_committee '{"topic": "Should I reduce tech exposure and rotate to energy?"}'
```
Triggers bull/bear debate → risk review → PM final call with a structured recommendation.

## Useful environment variables

- `LANGCHAIN_PROVIDER`, `<PROVIDER>_API_KEY`, `<PROVIDER>_BASE_URL`, `LANGCHAIN_MODEL_NAME` — LLM config (see `agent/.env.example`)
- `TUSHARE_TOKEN` — optional; AKShare is used as A-share fallback
- `API_AUTH_KEY` — bearer token for non-loopback API access
- `TIMEOUT_SECONDS` — LLM call timeout (default 120)
- `TOKEN_THRESHOLD` — agent context auto-compact threshold (default 40000)
- `VIBE_TRADING_ENABLE_SHELL_TOOLS`, `VIBE_TRADING_ALLOWED_FILE_ROOTS`, `VIBE_TRADING_ALLOWED_RUN_ROOTS` — sandbox opt-ins
- `INDMONEY_MCP_URL`, `INDMONEY_TOKEN_URL`, `INDMONEY_ASSET_TYPES` (default `IND_STOCK,US_STOCK,MF`), `INDMONEY_HOLDINGS_TTL_SECONDS` (default 900), `VIBE_TRADING_ENABLE_INDMONEY` — INDMoney integration. Tokens at `~/.vibe-trading/indmoney/{token,client}.json` (mode 0600)
