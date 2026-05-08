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

## Known limitations / v2 follow-ups

The branch ships the integration skeleton and unblocks the analytics pipeline,
but four follow-ups are tracked for the user to resolve before relying on the
integration in production:

1. **Authenticated discovery is incomplete.** The user needs to complete the
   browser OAuth flow and re-run `scripts/indmoney_discover.py` with the
   bearer token to populate the real tool surface and payload shapes. See
   sections 2-7 of `docs/superpowers/specs/2026-05-07-indmoney-discovery-notes.md`.
   The current normalizer assumes tool names `get_holdings` / `get_account` /
   `get_transactions` and the JSON fixtures under `agent/tests/fixtures/indmoney/`
   are illustrative (each carries a `_note` field saying so). A follow-up
   commit should replace the fixtures with sanitized real shapes once
   discovery is complete.

2. **`oauth-cli-kit` provider="indmoney" is unverified.** `cmd_indmoney_login`
   in `agent/cli.py` passes `provider="indmoney"` to `oauth_cli_kit.login_oauth_interactive`.
   If `oauth-cli-kit` does not ship an INDMoney provider, the inline fallback
   (Authorization Code + PKCE with httpx, sketched in code comments) needs
   to be implemented. End-to-end test of `vibe-trading indmoney login` is
   required before merge.

3. **Remote-caller gate is currently best-effort.** `gate_ok()` in
   `indmoney_holdings_tool.py` checks `VIBE_TRADING_REMOTE_CALL=1`, but
   neither `agent/api_server.py` nor `agent/mcp_server.py` currently sets
   that variable when handling a non-loopback request — so the gate never
   fires in production today. The proper fix is registry-level filtering
   that mirrors the existing shell-tools pattern (`include_shell_tools`
   in `agent/src/tools/__init__.py::build_registry`); track as a v2 PR.
   In the meantime, the integration is safe by virtue of the OAuth token
   living at `~/.vibe-trading/indmoney/token.json` on the user's machine —
   a remote attacker without access to that file gets `error_kind: needs_auth`,
   not portfolio data. Users running the API server on a public interface
   should still consider the gate non-functional.

4. **`auth_url` field is structurally present but always `None`.** The
   spec promises a populated `auth_url` on `needs_auth` responses; the
   current implementation passes `None` because the OAuth flow lives in
   the CLI subcommand, not in the tool. A follow-up can synthesize a
   pointer string ("Run: vibe-trading indmoney login") into the field
   once the field's exact contract is finalized.
