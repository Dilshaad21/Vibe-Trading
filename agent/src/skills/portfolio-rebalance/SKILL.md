---
name: portfolio-rebalance
description: Analyze current INDMoney portfolio concentration and plan a rebalance when the user asks for target weights, trade sizes, or portfolio structure.
category: recipe
---

# Portfolio rebalance

Use this recipe for portfolio concentration or rebalance requests. State the scope, source time, assumptions, and whether the result is analysis or an executable order. Respect any user-stated constraints on eligible assets and positions.

## Current holdings

For a current portfolio request, call `indmoney_holdings(force_refresh=true)`. If it returns an authentication or upstream error, surface that error and stop the current-holdings analysis. If it returns no relevant holdings, say so. Use the snapshot's `currency`; INDMoney values are converted to USD by default, but can be configured to remain INR.

For a **US stock sleeve** request, call `us_portfolio_rebalance(force_refresh=true)` for deterministic weights and concentration. This tool selects `asset_class=us_equity` holdings and the `US_STOCK_WALLET` investment row. Do not use `cash.cash_usd` as US buying power: it is based on INDMoney's broader Liquid category. The tool's `snapshot_path`, `from_cache`, and `asof` fields describe data provenance; `asof` may be absent.

If live INDMoney access fails, you may pass a known holdings file as `snapshot_path` for historical analysis. Label that output as a saved snapshot and give its `snapshot_file_mtime_utc`; do not describe it as current.

## Recommendation and sizing

Use `macro_snapshot()` when current macro context materially affects the proposed allocation; note partial or stale data. Choose target weights from the user's stated objectives and constraints, with clear reasoning. Neither the skill nor the calculator supplies investment targets automatically. Do not infer that a previously held asset remains in the current portfolio.

For selected **existing US stocks**, pass `target_weights_pct={"SYMBOL": percent, ...}` to `us_portfolio_rebalance`. Each percentage applies to the full US stocks plus US wallet sleeve. Omitted holdings remain at their current dollar values; the US wallet absorbs net buys and sells. Check `funded_by_wallet_and_sells` and `funding_gap_usd` before describing a plan as funded. The tool reports approximate share quantities from snapshot implied prices; verify live prices, fractional-share rules, fees, and taxes before execution. For a new ticker, research and verify its ticker and current quote separately before planning an order.

For broader asset-class requests, use `indmoney_holdings()` totals and `assets_by_class`, with the scope and currency stated. Do not use the US sleeve calculator for non-US positions or treat its weights as whole-account weights. Flag concentrated positions and explain the effect of any proposed changes. Avoid relying on `unrealized_pnl` alone for US gain estimates because FX conversion may distort it.

Present a compact table of current and target weights, dollar changes, and remaining wallet or cash, followed by the main risks and assumptions. The output is a read-only proposal; place orders only on a separate explicit request through the project's authorized trading flow.
