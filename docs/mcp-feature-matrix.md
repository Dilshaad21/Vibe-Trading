# MCP feature matrix (preset → recipe mapping)

Tracks which swarm presets have a recipe-skill replacement (works via MCP
without a second LLM) vs which still require a configured LLM provider.

## Status legend

- 🟢 **MCP-ready** — has a recipe skill, no LLM creds required.
- 🟡 **Pending** — could be replaced by a recipe in principle; not yet written.
- 🔴 **Swarm-only** — genuinely needs multi-voice adversarial debate; recipe replacement is not on the roadmap. Set `LANGCHAIN_PROVIDER` + `<PROVIDER>_API_KEY` to opt in.

## Mapping

| Preset | Status | Recipe skill |
|---|---|---|
| `macro_rates_fx_desk` | 🟢 | `macro-rates-fx-analysis` |
| `portfolio_review_board` | 🟢 | `portfolio-rebalance` |
| `fundamental_research_team` | 🟢 (single ticker) | `equity-fundamental-deep-dive` |
| `equity_research_team` | 🟡 | — |
| `factor_research_committee` | 🟡 | — |
| `ml_quant_lab` | 🟡 | — |
| `pairs_research_lab` | 🟡 | — |
| `statistical_arbitrage_desk` | 🟡 | — |
| `technical_analysis_panel` | 🟡 | — |
| `risk_committee` | 🟡 | — |
| `etf_allocation_desk` | 🟡 | — |
| `earnings_research_desk` | 🟡 | — |
| `sector_rotation_team` | 🟡 | — |
| `credit_research_team` | 🟡 | — |
| `convertible_bond_team` | 🟡 | — |
| `commodity_research_team` | 🟡 | — |
| `fund_selection_panel` | 🟡 | — |
| `quant_strategy_desk` | 🟡 | — |
| `derivatives_strategy_desk` | 🟡 | — |
| `global_equities_desk` | 🟡 | — |
| `global_allocation_committee` | 🟡 | — |
| `macro_strategy_forum` | 🟡 | — |
| `crypto_research_lab` | 🟡 | — |
| `crypto_trading_desk` | 🟡 | — |
| `investment_committee` | 🔴 | (multi-voice debate — opt in to swarm) |
| `geopolitical_war_room` | 🔴 | (qualitative synthesis — opt in to swarm) |
| `event_driven_task_force` | 🔴 | (special-situation reasoning — opt in to swarm) |
| `sentiment_intelligence_team` | 🔴 | (news / sentiment interpretation — opt in to swarm) |
| `social_alpha_team` | 🔴 | (social-media interpretation — opt in to swarm) |

## Adding a new recipe

1. Identify the preset's underlying data needs.
2. Confirm an MCP tool exists for each (or add one — see `agent/src/integrations/macro/` for the pattern).
3. Write `agent/src/skills/<recipe-name>/SKILL.md` with `category: recipe`. Body is a step-by-step tool-call sequence + a synthesis prompt.
4. Update the row in this table.
5. Add a regression test in `agent/tests/test_recipe_skills_loadable.py` asserting the new skill loads.
