"""Pluggable destinations. Pick one with SINK=sqlite|csv|google_sheets|hubspot."""

from __future__ import annotations

from ..config import Settings
from .base import Sink
from .csv_sink import CsvSink
from .google_sheets import GoogleSheetsSink
from .hubspot import HubSpotSink
from .sqlite_sink import SqliteSink

__all__ = ["Sink", "build_sink", "CsvSink", "SqliteSink", "GoogleSheetsSink", "HubSpotSink"]


def build_sink(settings: Settings) -> Sink:
    if settings.sink == "sqlite":
        return SqliteSink(settings.data_dir / "crm.db")
    if settings.sink == "csv":
        return CsvSink(settings.data_dir / "leads.csv")
    if settings.sink == "google_sheets":
        return GoogleSheetsSink(settings.google_sheets_webhook_url)
    if settings.sink == "hubspot":
        return HubSpotSink(settings.hubspot_token)
    raise ValueError(f"unknown SINK={settings.sink}")
