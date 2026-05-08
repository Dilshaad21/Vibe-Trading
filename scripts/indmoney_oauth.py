#!/usr/bin/env python3
"""One-shot OAuth (Authorization Code + PKCE) for mcp.indmoney.com.

Run interactively. Steps:
  1. Dynamic Client Registration (RFC 7591) → client_id + client_secret
  2. PKCE code_verifier + code_challenge
  3. Open browser to /authorize
  4. Listen on 127.0.0.1:<port>/callback
  5. Exchange the code at /token (client_secret_post)
  6. Persist client credentials → ~/.vibe-trading/indmoney/client.json (0600)
  7. Persist tokens via TokenCache → ~/.vibe-trading/indmoney/token.json (0600)

After completion:
  INDMONEY_ACCESS_TOKEN=$(python -c 'import json; print(json.load(open("/Users/'$USER'/.vibe-trading/indmoney/token.json"))["access_token"])') \\
    python scripts/indmoney_discover.py
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

# Ensure agent/ is on sys.path so we can use TokenCache.
_AGENT = Path(__file__).resolve().parent.parent / "agent"
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from src.integrations.indmoney.auth import Token, TokenCache  # noqa: E402

ISSUER = "https://mcp.indmoney.com/"
AUTHORIZE_URL = "https://mcp.indmoney.com/authorize"
TOKEN_URL = "https://mcp.indmoney.com/token"
REGISTRATION_URL = "https://mcp.indmoney.com/register"
SCOPE = "portfolio:read"
DEFAULT_PORT = 8765
CLIENT_NAME = "Vibe-Trading (one-shot OAuth)"
CLIENT_FILE = Path("~/.vibe-trading/indmoney/client.json").expanduser()


# ---------- helpers ----------

def _http_post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method="POST",
                  headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_form(url: str, body: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = Request(url, data=data, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded",
                           "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _save_client(client_id: str, client_secret: str) -> None:
    CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CLIENT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"client_id": client_id,
                                "client_secret": client_secret,
                                "issuer": ISSUER,
                                "issued_at": int(time.time())}, indent=2),
                    encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CLIENT_FILE)
    print(f"[ok] client credentials saved to {CLIENT_FILE} (mode 0600)")


# ---------- callback listener ----------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        _CallbackHandler.captured.update(params)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "error" in params:
            body = f"<h2>OAuth error</h2><p>{params.get('error')}: {params.get('error_description', '')}</p>"
        else:
            body = "<h2>Auth captured.</h2><p>You can close this tab and return to the terminal.</p>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # silence default access log


def _wait_for_callback(port: int, timeout_seconds: int = 300) -> dict[str, str]:
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1.0
    deadline = time.time() + timeout_seconds
    while not _CallbackHandler.captured and time.time() < deadline:
        server.handle_request()
    server.server_close()
    return dict(_CallbackHandler.captured)


# ---------- main ----------

def main() -> int:
    port = int(os.getenv("INDMONEY_OAUTH_PORT", str(DEFAULT_PORT)))
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    # Step 1: Dynamic Client Registration
    print(f"[1/5] Registering client at {REGISTRATION_URL} ...")
    reg = _http_post_json(REGISTRATION_URL, {
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
        "scope": SCOPE,
    })
    client_id = reg["client_id"]
    client_secret = reg.get("client_secret", "")
    if not client_secret:
        print("[fatal] registration response had no client_secret; this client expects a confidential client.")
        return 2
    _save_client(client_id, client_secret)

    # Step 2: PKCE
    code_verifier = _b64url(secrets.token_bytes(48))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = _b64url(secrets.token_bytes(16))

    auth_qs = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    auth_url = f"{AUTHORIZE_URL}?{auth_qs}"

    print(f"[2/5] Open this URL in your browser to authorize:\n\n  {auth_url}\n")
    print(f"[3/5] Waiting for redirect to {redirect_uri} (5 min timeout) ...")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    captured = _wait_for_callback(port)
    if not captured:
        print("[fatal] no callback received within timeout.")
        return 2
    if "error" in captured:
        print(f"[fatal] authorization error: {captured.get('error')} — {captured.get('error_description', '')}")
        return 2
    if captured.get("state") != state:
        print(f"[fatal] state mismatch: expected {state!r}, got {captured.get('state')!r}")
        return 2
    code = captured.get("code")
    if not code:
        print(f"[fatal] callback missing code: {captured!r}")
        return 2

    # Step 3: Exchange code for tokens
    print("[4/5] Exchanging code at /token ...")
    tok = _http_post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    access = tok.get("access_token")
    if not access:
        print(f"[fatal] token endpoint returned no access_token: {tok!r}")
        return 2
    refresh = tok.get("refresh_token", "")
    expires_in = int(tok.get("expires_in", 3600))
    account_id = tok.get("account_id") or tok.get("sub") or "default"

    # Step 4: Persist via TokenCache
    cache = TokenCache()
    cache.save(Token(
        access_token=access,
        refresh_token=refresh,
        expires_at=int(time.time()) + expires_in,
        account_id=account_id,
        issued_at=int(time.time()),
    ))
    print(f"[5/5] Tokens saved via TokenCache → {cache.path} (mode 0600)")
    print(f"        scope={tok.get('scope', SCOPE)}  account_id={account_id}  expires_in={expires_in}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
