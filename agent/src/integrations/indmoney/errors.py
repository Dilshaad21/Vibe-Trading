"""Structured error envelope for INDMoney tool responses.

Every INDMoney tool returns either a success payload or an envelope produced
by ``build_error``. Structured ``error_kind`` values let the agent decide
whether to retry, ask the user, or surface the error — instead of pattern
matching free-form strings.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorKind(str, Enum):
    """Coarse classification of why an INDMoney call failed."""

    NEEDS_AUTH = "needs_auth"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    STALE_TOKEN = "stale_token"
    CONFIG_MISSING = "config_missing"


def build_error(
    kind: ErrorKind,
    message: str,
    *,
    retry_after_seconds: int | None = None,
    auth_url: str | None = None,
) -> dict[str, Any]:
    """Return the canonical INDMoney error envelope."""
    return {
        "ok": False,
        "error_kind": kind.value,
        "message": message,
        "retry_after_seconds": retry_after_seconds,
        "auth_url": auth_url,
    }
