"""Tests for the append-only audit log."""

from __future__ import annotations

import re
from pathlib import Path

from src.integrations.indmoney.audit import append_audit


def test_append_writes_one_line(tmp_path: Path):
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="fetch_holdings", outcome="ok",
                 detail="42 positions")
    line = log.read_text().splitlines()
    assert len(line) == 1
    assert "acct1" in line[0]
    assert "fetch_holdings" in line[0]
    assert "42 positions" in line[0]


def test_append_redacts_token_substrings(tmp_path: Path):
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="refresh", outcome="ok",
                 detail="Authorization: Bearer abc123-fake-token-xyz")
    body = log.read_text()
    assert "abc123" not in body
    assert "<redacted>" in body


def test_append_format_is_iso_timestamp(tmp_path: Path):
    log = tmp_path / "audit.log"
    append_audit(log, account="acct1", action="x", outcome="ok", detail="")
    line = log.read_text().splitlines()[0]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
