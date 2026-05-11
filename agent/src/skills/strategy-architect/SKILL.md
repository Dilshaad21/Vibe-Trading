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
