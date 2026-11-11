"""SQLite persistence for analyses (one JSON document per review)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Analysis


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, created_at TEXT, title TEXT, body TEXT)")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, a: Analysis) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO analyses VALUES (?, ?, ?, ?)",
                       (a.id, a.created_at, a.source.title, a.model_dump_json()))

    def get(self, analysis_id: str) -> Analysis | None:
        with self._db() as db:
            row = db.execute("SELECT body FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        return Analysis.model_validate_json(row[0]) if row else None

    def all(self) -> list[Analysis]:
        with self._db() as db:
            rows = db.execute("SELECT body FROM analyses ORDER BY created_at DESC").fetchall()
        return [Analysis.model_validate_json(r[0]) for r in rows]

    def delete(self, analysis_id: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,)).rowcount > 0
