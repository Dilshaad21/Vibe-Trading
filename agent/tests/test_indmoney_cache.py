"""Tests for the INDMoney snapshot cache, index, and lock."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.integrations.indmoney.cache import (
    CACHE_DIR_NAME,
    SnapshotCache,
)


@pytest.fixture()
def cache(tmp_path: Path) -> SnapshotCache:
    return SnapshotCache(root=tmp_path)


def test_cache_dir_under_root(cache: SnapshotCache, tmp_path: Path):
    assert cache.dir == tmp_path / CACHE_DIR_NAME
    cache.dir.mkdir(parents=True, exist_ok=True)
    assert cache.dir.is_dir()


def test_put_and_get_within_ttl(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"hello": "world"}, ttl_seconds=60)
    fresh = cache.get("acct1", "holdings", "k")
    assert fresh is not None
    assert fresh["hello"] == "world"


def test_get_returns_none_after_ttl(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"x": 1}, ttl_seconds=0)
    time.sleep(0.05)
    assert cache.get("acct1", "holdings", "k") is None


def test_force_refresh_skips_cache(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"v": 1}, ttl_seconds=60)
    assert cache.get("acct1", "holdings", "k", force_refresh=True) is None


def test_corrupt_index_is_rebuilt_from_disk(cache: SnapshotCache):
    cache.put("acct1", "holdings", "k", {"v": 1}, ttl_seconds=60)
    (cache.dir / ".index.json").write_text("{not json")
    # Should not raise; rebuilds with no entries (raw files still exist).
    cache._load_index()  # private but tested
    assert isinstance(cache._index, dict)


def test_lock_is_released_on_exit(cache: SnapshotCache):
    with cache.lock("acct1", timeout_seconds=1):
        assert (cache.dir / "acct1.lock").exists()
    assert not (cache.dir / "acct1.lock").exists()


def test_lock_times_out_when_held(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    (cache.dir / "acct1.lock").write_text(str(int(time.time())))
    with pytest.raises(TimeoutError):
        with cache.lock("acct1", timeout_seconds=0.1):
            pass


def test_stale_lock_is_reclaimed(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    # Lock written with timestamp from 60 seconds ago — past stale threshold.
    (cache.dir / "acct1.lock").write_text(str(int(time.time()) - 60))
    with cache.lock("acct1", timeout_seconds=0.1, stale_seconds=30):
        pass  # should succeed


def test_prune_removes_old_snapshots(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    old = cache.dir / "old.json"
    old.write_text("{}")
    import os
    long_ago = time.time() - 86400 * 31
    os.utime(old, (long_ago, long_ago))
    cache.prune(max_age_days=30)
    assert not old.exists()


def test_prune_keeps_index_and_audit(cache: SnapshotCache):
    cache.dir.mkdir(parents=True, exist_ok=True)
    keep_index = cache.dir / ".index.json"
    keep_audit = cache.dir / "audit.log"
    keep_index.write_text("{}")
    keep_audit.write_text("")
    import os
    long_ago = time.time() - 86400 * 31
    os.utime(keep_index, (long_ago, long_ago))
    os.utime(keep_audit, (long_ago, long_ago))
    cache.prune(max_age_days=30)
    assert keep_index.exists()
    assert keep_audit.exists()
