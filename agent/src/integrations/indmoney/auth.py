"""OAuth token storage + refresh for INDMoney.

The actual OAuth code -> token exchange (browser launch, PKCE, etc.) is owned
by the CLI subcommand (``vibe-trading indmoney login``) which delegates to
``oauth-cli-kit``. This module is responsible only for:

  * Reading and writing the token file with mode 0o600
  * Atomic writes (temp file + rename) so a partial write never corrupts
    a previously-good token
  * Refreshing an expired access_token via the refresh_token, while
    leaving the on-disk token UNTOUCHED if the refresh fails
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_TOKEN_PATH = Path("~/.vibe-trading/indmoney/token.json").expanduser()


class StaleTokenError(RuntimeError):
    """Raised when a refresh attempt fails. The on-disk token is untouched."""


@dataclass(frozen=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: int  # epoch seconds
    account_id: str
    issued_at: int

    def is_expired(self, *, skew_seconds: int = 30) -> bool:
        return time.time() + skew_seconds >= self.expires_at


HttpPost = Callable[[str], dict[str, Any]]
"""Callable taking the refresh_token and returning a JSON token-endpoint response."""


class TokenCache:
    """File-backed token store with atomic write and refresh."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_TOKEN_PATH

    # ---- load / save ---------------------------------------------------

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return Token(**data)
        except TypeError:
            return None

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(token), indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ---- refresh -------------------------------------------------------

    def refresh(
        self,
        *,
        token_endpoint: str,
        http_post: HttpPost,
    ) -> Token:
        """Exchange refresh_token for a new access_token.

        Args:
            token_endpoint: URL - passed through to ``http_post`` for logging.
            http_post: Callable that performs the POST and returns the JSON.
                Injected so tests can stub the network without mocking httpx.

        Raises:
            StaleTokenError: refresh failed; on-disk token is untouched.
        """
        current = self.load()
        if current is None:
            raise StaleTokenError("no token to refresh")
        try:
            payload = http_post(current.refresh_token)
        except Exception as exc:
            raise StaleTokenError(f"refresh failed: {exc}") from exc

        access = payload.get("access_token")
        if not access:
            raise StaleTokenError("refresh response missing access_token")
        new = Token(
            access_token=access,
            refresh_token=payload.get("refresh_token") or current.refresh_token,
            expires_at=int(time.time()) + int(payload.get("expires_in", 3600)),
            account_id=current.account_id,
            issued_at=int(time.time()),
        )
        self.save(new)
        return new
