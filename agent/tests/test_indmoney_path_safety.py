"""Path-safety tests for the INDMoney cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.integrations.indmoney.cache import SnapshotCache


def test_account_id_with_traversal_does_not_escape_cache_dir(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    bad = "../../../etc/passwd"
    with pytest.raises((ValueError, OSError)):
        cache.put(bad, "holdings", "k", {"x": 1}, ttl_seconds=60)
    # No file may exist outside cache.dir.
    for child in tmp_path.rglob("*"):
        if child.is_file():
            assert tmp_path in child.resolve().parents or child.resolve().parent == tmp_path
            assert cache.dir in child.resolve().parents or child.resolve().parent == cache.dir


def test_lock_file_with_traversal_does_not_escape(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    cache.dir.mkdir(parents=True, exist_ok=True)
    bad = "../../boom"
    with pytest.raises((TimeoutError, OSError, ValueError)):
        with cache.lock(bad, timeout_seconds=0.1):
            pass
    assert not (tmp_path / "boom.lock").exists()
    assert not (tmp_path.parent / "boom.lock").exists()
