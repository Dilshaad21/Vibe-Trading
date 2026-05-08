"""Append-only INDMoney audit log.

One line per successful or failed MCP call. No PII. No tokens. Bearer
substrings are redacted defensively even if a caller forgets.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def _redact(text: str) -> str:
    return _BEARER_RE.sub("Bearer <redacted>", text)


def append_audit(path: Path, *, account: str, action: str, outcome: str,
                 detail: str = "") -> None:
    """Append one line to the audit log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    line = f"{ts}\t{account}\t{action}\t{outcome}\t{_redact(detail)}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
