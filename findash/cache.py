"""Persistent topic cache — last-known DataHub payloads in a small SQLite file.

On startup DataHub serves cached values immediately, so charts, quotes, and
watchlists appear instantly (and even offline) while a fresh network refresh runs
in the background. The cache is entirely best-effort: any failure — no disk, a
locked db, a non-JSON payload — disables it silently and the app runs exactly as
before.

All access happens on the GUI thread (DataHub marshals every publish there via a
queued signal), so a single connection is safe.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QStandardPaths


def _default_db_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    ) or str(Path.home() / ".findash" / "cache")
    return Path(base) / "topics.db"


class TopicCache:
    """SQLite-backed store of the newest value per topic (best-effort)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._conn: Optional[sqlite3.Connection] = None
        path = db_path or _default_db_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=True (default): every access must be on the
            # thread that created this connection. DataHub creates it on the GUI
            # thread (register_all_providers() is the first DataHub.instance()
            # call, before the event loop) and all cache access is GUI-thread —
            # that ordering is load-bearing.
            self._conn = sqlite3.connect(str(path))
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS cache "
                "(topic TEXT PRIMARY KEY, value TEXT NOT NULL, ts REAL NOT NULL)"
            )
            self._conn.commit()
        except (sqlite3.Error, OSError):
            self._conn = None  # disabled — every method below becomes a no-op

    def available(self) -> bool:
        return self._conn is not None

    def get(self, topic: str) -> Optional[tuple[Any, float]]:
        """(value, wall-clock timestamp) for ``topic``, or None if absent."""
        if self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT value, ts FROM cache WHERE topic = ?", (topic,)
            ).fetchone()
            if row is None:
                return None
            return json.loads(row[0]), float(row[1])
        except (sqlite3.Error, ValueError, TypeError):
            return None

    def put(self, topic: str, value: Any, ts: Optional[float] = None) -> None:
        if self._conn is None:
            return
        try:
            blob = json.dumps(value)  # only JSON-serializable payloads are cached
        except (TypeError, ValueError):
            return  # non-serializable payload — skip it, don't disturb the app
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(topic, value, ts) VALUES (?, ?, ?)",
                (topic, blob, ts if ts is not None else time.time()),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def put_many(self, items: list, ts: Optional[float] = None) -> None:
        """Persist many ``(topic, value)`` pairs in ONE transaction — a single
        fsync instead of one per topic. Non-serializable values are skipped."""
        if self._conn is None or not items:
            return
        now = ts if ts is not None else time.time()
        rows = []
        for topic, value in items:
            try:
                rows.append((topic, json.dumps(value), now))
            except (TypeError, ValueError):
                continue  # skip this one, keep the rest
        if not rows:
            return
        try:
            self._conn.executemany(
                "INSERT OR REPLACE INTO cache(topic, value, ts) VALUES (?, ?, ?)",
                rows,
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def prune(self, max_age_s: float = 7 * 24 * 3600, max_rows: int = 5000) -> None:
        """Drop entries older than ``max_age_s`` and cap the row count."""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "DELETE FROM cache WHERE ts < ?", (time.time() - max_age_s,)
            )
            self._conn.execute(
                "DELETE FROM cache WHERE topic NOT IN "
                "(SELECT topic FROM cache ORDER BY ts DESC LIMIT ?)",
                (max_rows,),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
