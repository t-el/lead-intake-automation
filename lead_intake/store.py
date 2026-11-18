"""Processing state: idempotency ledger + dead-letter queue (SQLite, zero setup)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    email TEXT PRIMARY KEY,
    sink_ref TEXT,
    score INTEGER,
    tier TEXT,
    processed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    step TEXT NOT NULL,
    error TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);
"""


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- idempotency ---------------------------------------------------------
    def is_processed(self, email: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM processed WHERE email = ?", (email,)).fetchone() is not None

    def mark_processed(self, email: str, sink_ref: str, score: int, tier: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO processed (email, sink_ref, score, tier) VALUES (?, ?, ?, ?)",
                (email, sink_ref, score, tier),
            )

    def processed(self) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM processed ORDER BY processed_at DESC, score DESC")]

    # --- dead-letter queue ---------------------------------------------------
    def add_dead_letter(self, email: Optional[str], step: str, error: str, payload: dict) -> int:
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO dead_letters (email, step, error, payload) VALUES (?, ?, ?, ?)",
                (email, step, error[:2000], json.dumps(payload, default=str)),
            )
            return int(cur.lastrowid)

    def dead_letters(self, include_resolved: bool = False) -> list[dict]:
        sql = "SELECT * FROM dead_letters" + ("" if include_resolved else " WHERE resolved_at IS NULL") + " ORDER BY id"
        with self._db() as db:
            rows = [dict(r) for r in db.execute(sql)]
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def get_dead_letter(self, dl_id: int) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM dead_letters WHERE id = ?", (dl_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d

    def resolve_dead_letter(self, dl_id: int) -> None:
        with self._db() as db:
            db.execute("UPDATE dead_letters SET resolved_at = CURRENT_TIMESTAMP WHERE id = ?", (dl_id,))
