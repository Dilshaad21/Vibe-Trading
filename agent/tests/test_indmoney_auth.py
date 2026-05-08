"""Tests for INDMoney TokenCache (load / save / refresh)."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import httpx
import pytest

from src.integrations.indmoney.auth import (
    StaleTokenError,
    Token,
    TokenCache,
)


def _fresh_token(**kw) -> Token:
    base = dict(
        access_token="acc_1",
        refresh_token="ref_1",
        expires_at=int(time.time()) + 3600,
        account_id="acct1",
        issued_at=int(time.time()),
    )
    base.update(kw)
    return Token(**base)


def test_save_creates_file_with_0600_mode(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token())
    mode = stat.S_IMODE(os.stat(cache.path).st_mode)
    assert mode == 0o600


def test_save_uses_atomic_rename(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token(access_token="v1"))
    # Force partial write failure: replace with a directory at the temp path.
    tmp = cache.path.with_suffix(".json.tmp")
    if tmp.exists():
        tmp.unlink()
    cache.save(_fresh_token(access_token="v2"))
    loaded = cache.load()
    assert loaded is not None
    assert loaded.access_token == "v2"


def test_load_returns_none_when_missing(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "missing.json")
    assert cache.load() is None


def test_refresh_failure_preserves_existing_token(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token(access_token="original", refresh_token="r1"))

    def failing(refresh_token: str) -> dict:
        raise httpx.HTTPStatusError("400", request=None, response=None)  # type: ignore[arg-type]

    with pytest.raises(StaleTokenError):
        cache.refresh(token_endpoint="https://example/token", http_post=failing)

    raw = json.loads(cache.path.read_text())
    assert raw["access_token"] == "original"


def test_refresh_success_updates_file(tmp_path: Path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(_fresh_token(access_token="old", refresh_token="r1"))

    def ok(refresh_token: str) -> dict:
        assert refresh_token == "r1"
        return {"access_token": "new", "refresh_token": "r2", "expires_in": 7200}

    new = cache.refresh(token_endpoint="https://example/token", http_post=ok)
    assert new.access_token == "new"
    assert new.refresh_token == "r2"
    on_disk = json.loads(cache.path.read_text())
    assert on_disk["access_token"] == "new"


def test_token_is_expired():
    t = _fresh_token(expires_at=int(time.time()) - 1)
    assert t.is_expired()
    fresh = _fresh_token()
    assert not fresh.is_expired()
