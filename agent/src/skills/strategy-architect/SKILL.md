---
name: strategy-architect
description: Comprehensive multi-dimensional analysis recipe. Fuses macroeconomics, news/catalysts, fundamentals, and technicals into multi-horizon trade plans (short/medium/long). Adaptive to input — works on a single ticker, a whole portfolio, or a theme. Default entry point for any "should I buy/hold/sell" or "what's my strategy on X" question.
category: recipe
---

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
