"""Company enrichment from the lead's email domain.

``MockEnricher`` uses a local fixture so the project runs offline.
``HttpEnricher`` calls any JSON enrichment API (Clearbit-style, Apollo, your own service).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

import httpx

from .config import Settings
from .models import Enrichment
from .retry import PermanentError, TransientError, classify_http_status

log = logging.getLogger("lead_intake.enrich")

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "proton.me", "aol.com", "live.com",
}
FIXTURE = Path(__file__).resolve().parent.parent / "samples" / "companies.json"


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


class MockEnricher:
    """Deterministic enrichment. Two special domains simulate real-world API failures:

    * ``flaky-co.com``  fails twice with a transient error, then succeeds (shows retries working)
    * ``down-api.com``  always fails transiently (shows the dead-letter queue working)
    """

    def __init__(self, fixture: Path = FIXTURE):
        self.companies = json.loads(fixture.read_text()) if fixture.exists() else {}
        self._calls: dict[str, int] = defaultdict(int)

    def enrich(self, email: str) -> Enrichment:
        domain = domain_of(email)
        self._calls[domain] += 1
        if domain == "flaky-co.com" and self._calls[domain] <= 2:
            raise TransientError(f"enrichment API timeout for {domain} (simulated)")
        if domain == "down-api.com":
            raise TransientError(f"enrichment API 503 for {domain} (simulated)")
        if domain in FREE_EMAIL_DOMAINS:
            return Enrichment(domain=domain, is_free_email=True)
        data = self.companies.get(domain)
        if data:
            return Enrichment(domain=domain, **data)
        guessed = domain.split(".")[0].replace("-", " ").title()
        return Enrichment(domain=domain, company_name=guessed)


class HttpEnricher:
    def __init__(self, url: str, api_key: str = "", timeout: float = 10.0):
        if not url:
            raise ValueError("ENRICHMENT_URL is required when ENRICHMENT_MODE=http")
        self.url = url
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout

    def enrich(self, email: str) -> Enrichment:
        domain = domain_of(email)
        if domain in FREE_EMAIL_DOMAINS:
            return Enrichment(domain=domain, is_free_email=True)
        try:
            resp = httpx.get(self.url, params={"domain": domain}, headers=self.headers, timeout=self.timeout)
        except httpx.TransportError as exc:
            raise TransientError(f"enrichment transport error: {exc}") from exc
        if resp.status_code == 404:
            return Enrichment(domain=domain)
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(f"enrichment HTTP {resp.status_code}")
        body = resp.json()
        return Enrichment(
            domain=domain,
            company_name=body.get("name") or body.get("company_name"),
            industry=body.get("industry"),
            employees=body.get("employees") or body.get("employee_count"),
            country=body.get("country"),
        )


def build_enricher(settings: Settings):
    if settings.enrichment_mode == "http":
        return HttpEnricher(settings.enrichment_url, settings.enrichment_api_key)
    if settings.enrichment_mode != "mock":
        raise PermanentError(f"unknown ENRICHMENT_MODE={settings.enrichment_mode}")
    return MockEnricher()
