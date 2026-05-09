# Macro snapshot integration

Read-only data fetcher for the cross-asset macro state — central-bank
rates, US Treasury yields, FX, commodities. Powers the
`macro_snapshot` MCP tool and the `macro-rates-fx-analysis` recipe
skill.

## Sources (no API keys required)

| Field group | Source | Endpoint |
|---|---|---|
| Central-bank rates | FRED public CSV | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>` |
| US Treasury yields | FRED public CSV | same |
| FX | yfinance | `^TICKER` / `=X` symbols |
| Commodities | yfinance | futures contracts (`BZ=F`, `CL=F`, `GC=F`) |

Per-field source mapping is in `agent/src/integrations/macro/snapshot.py::_FIELDS`.

## Failure handling

`fetch_macro_snapshot()` never raises. If a single source fails:
- The corresponding field becomes `null`
- A structured entry lands in `_errors` with `{field, source, reason}`
- All other fields keep their values

The MCP tool surfaces `_errors` to the caller so an agent can decide
whether to proceed or escalate.

## Cache

Snapshots are written to `agent/uploads/macro/snapshot.json` with a
1-hour TTL by default (override with `MACRO_SNAPSHOT_TTL_SECONDS`).
The cache is single-file and atomic (temp file + rename).
