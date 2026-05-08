"""Snapshot cache + index + per-account concurrent-fetch lock.

Cache files live under ``<root>/indmoney/``. The index is a JSON dict at
``.index.json`` mapping ``"<account>:<kind>:<key>"`` → ``{path, asof, expires_at}``.
A corrupt index is silently rebuilt as empty (the raw snapshot files on disk
remain authoritative for analytics — the index is just a freshness shortcut).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

CACHE_DIR_NAME = "indmoney"
INDEX_FILE = ".index.json"
AUDIT_FILE = "audit.log"

_PROTECTED_FILES = {INDEX_FILE, AUDIT_FILE}


class SnapshotCache:
    """TTL-gated snapshot cache for INDMoney responses."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / CACHE_DIR_NAME
        self._index: dict[str, dict[str, Any]] = {}
        self._index_loaded = False

    # ---- index ---------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> None:
        self._ensure_dir()
        path = self.dir / INDEX_FILE
        if not path.exists():
            self._index = {}
            self._index_loaded = True
            return
        try:
            self._index = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(self._index, dict):
                raise ValueError("index is not a dict")
        except Exception as exc:
            logger.warning("indmoney: index corrupt (%s) — rebuilding empty", exc)
            self._index = {}
        self._index_loaded = True

    def _save_index(self) -> None:
        self._ensure_dir()
        path = self.dir / INDEX_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._index, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    # ---- get / put -----------------------------------------------------

    @staticmethod
    def _key(account: str, kind: str, key: str) -> str:
        return f"{account}:{kind}:{key}"

    def put(self, account: str, kind: str, key: str, value: dict[str, Any],
            ttl_seconds: int) -> Path:
        """Persist a snapshot and update the index. Returns the file path."""
        if not self._index_loaded:
            self._load_index()
        self._ensure_dir()
        asof = int(time.time())
        filename = f"{account}_{kind}_{asof}.json"
        path = self.dir / filename
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        self._index[self._key(account, kind, key)] = {
            "path": filename,
            "asof": asof,
            "expires_at": asof + max(0, ttl_seconds),
        }
        self._save_index()
        return path

    def get(self, account: str, kind: str, key: str, *,
            force_refresh: bool = False) -> dict[str, Any] | None:
        """Return cached snapshot dict if fresh; else None."""
        if force_refresh:
            return None
        if not self._index_loaded:
            self._load_index()
        entry = self._index.get(self._key(account, kind, key))
        if not entry:
            return None
        if entry.get("expires_at", 0) <= time.time():
            return None
        path = self.dir / entry["path"]
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("indmoney: snapshot %s unreadable (%s)", path, exc)
            return None

    # ---- lock ----------------------------------------------------------

    @contextlib.contextmanager
    def lock(self, account: str, *, timeout_seconds: float = 30.0,
             stale_seconds: float = 30.0) -> Iterator[None]:
        """Per-account fetch lock. Reclaims locks older than ``stale_seconds``."""
        self._ensure_dir()
        path = self.dir / f"{account}.lock"
        deadline = time.time() + timeout_seconds
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(int(time.time())).encode("utf-8"))
                os.close(fd)
                break
            except FileExistsError:
                # Reclaim if stale.
                try:
                    held_at = int(path.read_text(encoding="utf-8").strip() or "0")
                except Exception:
                    held_at = 0
                if time.time() - held_at > stale_seconds:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue
                if time.time() >= deadline:
                    raise TimeoutError(f"INDMoney lock for {account!r} held > {timeout_seconds}s")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    # ---- prune ---------------------------------------------------------

    def prune(self, *, max_age_days: int = 30) -> int:
        """Delete snapshot files older than ``max_age_days``. Returns count."""
        if not self.dir.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for child in self.dir.iterdir():
            if child.name in _PROTECTED_FILES:
                continue
            if child.suffix == ".lock":
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    child.unlink()
                    removed += 1
            except FileNotFoundError:
                pass
        return removed
