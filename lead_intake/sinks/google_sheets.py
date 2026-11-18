from __future__ import annotations

import httpx

from ..models import ProcessedLead
from ..retry import TransientError, classify_http_status


class GoogleSheetsSink:
    """Writes a row through a Google Apps Script web app bound to the sheet.

    No service-account JSON to manage: deploy ``docs/google-apps-script.js`` as a web app and
    put its URL in GOOGLE_SHEETS_WEBHOOK_URL. The script upserts on the email column.
    """

    name = "google_sheets"

    def __init__(self, webhook_url: str, client: httpx.Client | None = None):
        if not webhook_url:
            raise ValueError("GOOGLE_SHEETS_WEBHOOK_URL is required when SINK=google_sheets")
        self.url = webhook_url
        self.client = client or httpx.Client(timeout=15.0, follow_redirects=True)

    def write(self, lead: ProcessedLead) -> str:
        try:
            resp = self.client.post(self.url, json=lead.flat())
        except httpx.TransportError as exc:
            raise TransientError(f"sheets transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(f"sheets HTTP {resp.status_code}")
        return f"sheets:{lead.lead.email}"
