# INDMoney MCP Integration

Read-only INDMoney portfolio access: holdings, transactions, cash. Powers the
existing `trade_journal_tool` and `shadow_account_tool` analytics with no
parser changes.

## One-time setup

```bash
pip install -e ".[dev]"      # ensures oauth-cli-kit is on the path
vibe-trading indmoney login  # opens browser for OAuth
vibe-trading indmoney status # confirms token and expiry
```

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `INDMONEY_MCP_URL` | `https://mcp.indmoney.com/mcp` | Override for staging |
| `INDMONEY_TOKEN_URL` | `https://mcp.indmoney.com/oauth/token` | OAuth token endpoint |
| `INDMONEY_TOKEN_PATH` | `~/.vibe-trading/indmoney/token.json` | Token store |
| `INDMONEY_HOLDINGS_TTL_SECONDS` | `900` | Holdings cache TTL (15 min) |
| `INDMONEY_TXNS_TTL_SECONDS` | `86400` | Transactions cache TTL (24 h) |
| `VIBE_TRADING_ENABLE_INDMONEY` | unset | Required for non-loopback API/MCP-SSE callers |

## Tools (auto-published via the registry)

| Tool | Use it for |
|---|---|
| `indmoney_holdings` | Current positions + cash |
| `indmoney_transactions` | Date-range trade history → CSV consumable by `trade_journal` |
| `indmoney_sync` | Force-refresh holdings + last 30 days of transactions |

## Manual test recipe

```bash
# 1. Authenticate
vibe-trading indmoney login

# 2. Pull holdings
vibe-trading run -p "Use indmoney_holdings to fetch my current portfolio"

# 3. Pull last 30 days and feed to trade journal
vibe-trading run -p "Use indmoney_sync, then run trade_journal on the resulting csv_path"
```

## Output files

All cache + snapshot files land under `agent/uploads/indmoney/` (already inside
the project's default sandbox roots — no allow-list change needed):

```
agent/uploads/indmoney/
├── .index.json                              # cache freshness index
├── audit.log                                # one line per MCP call
├── <account>_holdings_<ts>.json             # holdings snapshot
├── <account>_transactions_<ts>.json         # transactions snapshot
├── <account>_<start>_<end>_txns.csv         # FIFO-eligible trades CSV
└── <account>_<start>_<end>_events.csv       # dividends + splits + unknowns
```

The events CSV is intentionally separate so the existing `trade_journal_tool`
is never confused by non-trade rows (`_normalize_side` would silently coerce
them to `"buy"`).
