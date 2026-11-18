from __future__ import annotations

import csv
from pathlib import Path

from ..models import ProcessedLead
from .sqlite_sink import COLUMNS


class CsvSink:
    """Append-only CSV (opens straight in Excel / Google Sheets). Skips emails already present."""

    name = "csv"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _existing(self) -> set[str]:
        if not self.path.exists():
            return set()
        with self.path.open(newline="") as f:
            return {row["email"] for row in csv.DictReader(f)}

    def write(self, lead: ProcessedLead) -> str:
        row = lead.flat()
        if row["email"] in self._existing():
            return f"csv:{row['email']}:exists"
        new_file = not self.path.exists()
        with self.path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        return f"csv:{row['email']}"
