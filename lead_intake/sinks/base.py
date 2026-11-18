from __future__ import annotations

from typing import Protocol

from ..models import ProcessedLead


class Sink(Protocol):
    name: str

    def write(self, lead: ProcessedLead) -> str:
        """Persist the lead and return a reference (row id, CRM id...). Must be safe to call twice."""
        ...
