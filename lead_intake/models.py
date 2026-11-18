from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class LeadIn(BaseModel):
    """What a website form / Typeform / Webflow webhook sends us."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    company: Optional[str] = None
    title: Optional[str] = None
    message: Optional[str] = Field(default=None, max_length=5000)
    budget: Optional[str] = None
    source: str = "website"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class Enrichment(BaseModel):
    domain: str
    company_name: Optional[str] = None
    industry: Optional[str] = None
    employees: Optional[int] = None
    country: Optional[str] = None
    is_free_email: bool = False


class Score(BaseModel):
    score: int = Field(ge=0, le=100)
    tier: str  # hot | warm | cold
    summary: str
    reasons: list[str] = []
    scored_by: str  # heuristic | llm:<model>


class ProcessedLead(BaseModel):
    lead: LeadIn
    enrichment: Enrichment
    score: Score

    def flat(self) -> dict:
        return {
            "email": self.lead.email,
            "name": self.lead.name,
            "company": self.enrichment.company_name or self.lead.company or "",
            "title": self.lead.title or "",
            "domain": self.enrichment.domain,
            "industry": self.enrichment.industry or "",
            "employees": self.enrichment.employees or "",
            "country": self.enrichment.country or "",
            "source": self.lead.source,
            "budget": self.lead.budget or "",
            "score": self.score.score,
            "tier": self.score.tier,
            "summary": self.score.summary,
            "scored_by": self.score.scored_by,
        }
