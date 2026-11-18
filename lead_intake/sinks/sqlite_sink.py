from __future__ import annotations

import sqlite3
from pathlib import Path

from ..models import ProcessedLead

COLUMNS = ["email", "name", "company", "title", "domain", "industry", "employees", "country",
           "source", "budget", "score", "tier", "summary", "scored_by"]


class SqliteSink:
    """Local 'CRM' table. Upserts on email, so replays never create duplicates."""

    name = "sqlite"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            cols = ", ".join(f"{c} TEXT" for c in COLUMNS if c != "email")
            db.execute(f"CREATE TABLE IF NOT EXISTS leads (email TEXT PRIMARY KEY, {cols}, "
                       "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    def write(self, lead: ProcessedLead) -> str:
        row = lead.flat()
        placeholders = ", ".join("?" for _ in COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in COLUMNS if c != "email")
        with sqlite3.connect(self.path) as db:
            db.execute(
                f"INSERT INTO leads ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
                f"ON CONFLICT(email) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP",
                [str(row[c]) for c in COLUMNS],
            )
        return f"sqlite:{row['email']}"

    def all(self) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM leads ORDER BY CAST(score AS INTEGER) DESC")]
