from __future__ import annotations

import httpx

from ..models import ProcessedLead
from ..retry import TransientError, classify_http_status

API = "https://api.hubapi.com/crm/v3/objects/contacts"


class HubSpotSink:
    """Creates a HubSpot contact (private-app token). A 409 means it already exists: treated as success."""

    name = "hubspot"

    def __init__(self, token: str, client: httpx.Client | None = None, api_url: str = API):
        if not token:
            raise ValueError("HUBSPOT_TOKEN is required when SINK=hubspot")
        self.api_url = api_url
        self.client = client or httpx.Client(timeout=15.0, headers={"Authorization": f"Bearer {token}"})

    def write(self, lead: ProcessedLead) -> str:
        row = lead.flat()
        first, _, last = row["name"].partition(" ")
        props = {
            "email": row["email"], "firstname": first, "lastname": last, "company": row["company"],
            "jobtitle": row["title"], "hs_lead_status": "NEW",
            "lead_score_ai": str(row["score"]), "lead_summary_ai": row["summary"],
        }
        try:
            resp = self.client.post(self.api_url, json={"properties": props})
        except httpx.TransportError as exc:
            raise TransientError(f"hubspot transport error: {exc}") from exc
        if resp.status_code == 409:
            return f"hubspot:{row['email']}:exists"
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(f"hubspot HTTP {resp.status_code}: {resp.text[:200]}")
        return f"hubspot:{resp.json().get('id')}"
