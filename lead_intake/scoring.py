"""Lead scoring: an LLM (any OpenAI-compatible API) with a deterministic heuristic fallback.

The heuristic is used when no API key is configured, or when the LLM call fails / returns
garbage, so a bad AI response never blocks a lead from reaching the CRM.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from .config import Settings
from .models import Enrichment, LeadIn, Score
from .retry import TransientError, classify_http_status, retry_call

log = logging.getLogger("lead_intake.scoring")

SENIOR_TITLES = ("ceo", "founder", "owner", "cto", "coo", "vp", "head", "director", "partner", "president")
INTENT_WORDS = ("budget", "asap", "urgent", "this month", "automate", "automation", "integrate", "replace", "quote")


def tier_for(score: int, hot_threshold: int = 70) -> str:
    if score >= hot_threshold:
        return "hot"
    return "warm" if score >= 40 else "cold"


def _budget_value(budget: str | None) -> int:
    if not budget:
        return 0
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", budget)]
    if not nums:
        return 0
    value = max(nums)
    if re.search(r"\d\s*k\b", budget.lower()):
        value *= 1000
    return value


def heuristic_score(lead: LeadIn, enrichment: Enrichment, hot_threshold: int = 70) -> Score:
    score, reasons = 20, []
    if enrichment.is_free_email:
        score -= 10
        reasons.append("free email domain")
    else:
        score += 10
        reasons.append("business email")
    emp = enrichment.employees or 0
    if emp >= 200:
        score += 20
        reasons.append(f"{emp} employees")
    elif emp >= 20:
        score += 12
        reasons.append(f"{emp} employees")
    title = (lead.title or "").lower()
    if any(t in title for t in SENIOR_TITLES):
        score += 15
        reasons.append(f"decision maker ({lead.title})")
    budget = _budget_value(lead.budget)
    if budget >= 5000:
        score += 20
        reasons.append(f"budget {lead.budget}")
    elif budget >= 1000:
        score += 10
        reasons.append(f"budget {lead.budget}")
    msg = (lead.message or "").lower()
    hits = [w for w in INTENT_WORDS if w in msg]
    if hits:
        score += min(15, 5 * len(hits))
        reasons.append("intent: " + ", ".join(hits))
    score = max(0, min(100, score))
    company = enrichment.company_name or lead.company or enrichment.domain
    tier = tier_for(score, hot_threshold)
    summary = f"{lead.name} ({lead.title or 'unknown role'}) at {company}: {tier} lead, score {score}."
    return Score(score=score, tier=tier, summary=summary, reasons=reasons, scored_by="heuristic")


SYSTEM_PROMPT = (
    "You qualify inbound B2B leads for an automation agency. Reply ONLY with JSON: "
    '{"score": 0-100 integer, "summary": "one sentence", "reasons": ["short", "reasons"]}.'
)


class LLMScorer:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=20.0)

    def _call(self, lead: LeadIn, enrichment: Enrichment) -> dict:
        payload = {
            "model": self.s.openai_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"lead": lead.model_dump(), "company": enrichment.model_dump()})},
            ],
        }
        try:
            resp = self.client.post(
                f"{self.s.openai_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.s.openai_api_key}"},
            )
        except httpx.TransportError as exc:
            raise TransientError(f"LLM transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(f"LLM HTTP {resp.status_code}")
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def score(self, lead: LeadIn, enrichment: Enrichment) -> Score:
        data = retry_call(
            lambda: self._call(lead, enrichment),
            attempts=self.s.retry_attempts,
            base_delay=self.s.retry_base_delay,
            step="llm_score",
        )
        value = max(0, min(100, int(data["score"])))
        return Score(
            score=value,
            tier=tier_for(value, self.s.hot_threshold),
            summary=str(data.get("summary", ""))[:500],
            reasons=[str(r) for r in data.get("reasons", [])][:5],
            scored_by=f"llm:{self.s.openai_model}",
        )


class Scorer:
    """Facade: LLM when configured, heuristic otherwise or on any LLM failure."""

    def __init__(self, settings: Settings, llm: LLMScorer | None = None):
        self.s = settings
        self.llm = llm or (LLMScorer(settings) if settings.openai_api_key else None)

    def score(self, lead: LeadIn, enrichment: Enrichment) -> Score:
        if self.llm is not None:
            try:
                return self.llm.score(lead, enrichment)
            except Exception as exc:  # noqa: BLE001 - any LLM problem falls back, never blocks the lead
                log.warning("LLM scoring failed, using heuristic fallback", extra={"email": lead.email, "error": str(exc)})
        return heuristic_score(lead, enrichment, self.s.hot_threshold)
