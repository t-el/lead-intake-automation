"""FastAPI service.

* ``POST /webhook/lead``            full pure-Python pipeline (point your form/Typeform/Webflow here)
* ``POST /steps/enrich-score``      single step used by the n8n workflow (enrich + AI score)
* ``POST /steps/save``              single step used by the n8n workflow (idempotent write to the sink)
* ``GET/POST /dead-letters``        inspect, record (from n8n error branch) and replay failures
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import asdict
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import __version__
from .config import get_settings
from .logging_setup import setup_logging
from .models import Enrichment, LeadIn, ProcessedLead, Score
from .pipeline import Pipeline
from .retry import PermanentError, TransientError

log = logging.getLogger("lead_intake.api")


class FailureIn(BaseModel):
    email: Optional[str] = None
    step: str = "n8n"
    error: str
    payload: dict[str, Any] = {}


class SaveIn(BaseModel):
    lead: LeadIn
    enrichment: Enrichment
    score: Score


def create_app(pipeline: Pipeline | None = None) -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_json)
    app = FastAPI(title="Lead Intake Automation", version=__version__)
    app.state.pipeline = pipeline or Pipeline(settings)

    @app.exception_handler(TransientError)
    async def transient_handler(_req: Request, exc: TransientError) -> JSONResponse:
        # 503 tells n8n / the caller "retry later" (n8n's Retry On Fail kicks in)
        return JSONResponse(status_code=503, content={"error": str(exc), "retryable": True})

    @app.exception_handler(PermanentError)
    async def permanent_handler(_req: Request, exc: PermanentError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc), "retryable": False})

    def check_secret(x_webhook_secret: str | None = Header(default=None)) -> None:
        if settings.webhook_secret and not hmac.compare_digest(x_webhook_secret or "", settings.webhook_secret):
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    def pl() -> Pipeline:
        return app.state.pipeline

    @app.get("/health")
    def health() -> dict:
        p = pl()
        return {"ok": True, "version": __version__, "sink": p.sink.name, "notifier": p.notifier.name,
                "ai": "llm" if p.scorer.llm else "heuristic"}

    @app.post("/webhook/lead", dependencies=[Depends(check_secret)])
    def webhook_lead(payload: dict[str, Any], response: Response) -> dict:
        result = pl().process(payload)
        if result.status == "invalid":
            raise HTTPException(status_code=422, detail={"error": result.error, "dead_letter_id": result.dead_letter_id})
        # dead_lettered still returns 202: the lead is safely queued, the form provider should not resend
        response.status_code = {"processed": 201, "duplicate": 200, "dead_lettered": 202}[result.status]
        return asdict(result)

    @app.post("/steps/enrich-score", dependencies=[Depends(check_secret)])
    def step_enrich_score(lead: LeadIn) -> dict:
        p = pl()
        duplicate = p.store.is_processed(lead.email)
        enrichment, score = p.enrich_and_score(lead)
        return {"duplicate": duplicate, "lead": lead.model_dump(), "enrichment": enrichment.model_dump(),
                "score": score.model_dump()}

    @app.post("/steps/save", dependencies=[Depends(check_secret)])
    def step_save(body: SaveIn) -> dict:
        ref = pl().save(ProcessedLead(lead=body.lead, enrichment=body.enrichment, score=body.score))
        return {"saved": True, "sink_ref": ref}

    @app.post("/mock/slack")
    def mock_slack(body: dict[str, Any]) -> dict:
        """Stand-in for a Slack incoming webhook so the n8n workflow runs offline."""
        from .notify import ConsoleNotifier

        ConsoleNotifier(settings.data_dir / "alerts.log").send("Slack (mock)", str(body.get("text", "")))
        return {"ok": True}

    @app.get("/leads")
    def leads() -> list[dict]:
        return pl().store.processed()

    @app.get("/dead-letters")
    def dead_letters(include_resolved: bool = False) -> list[dict]:
        return pl().store.dead_letters(include_resolved)

    @app.post("/dead-letters", dependencies=[Depends(check_secret)], status_code=201)
    def record_failure(body: FailureIn) -> dict:
        dl_id = pl().store.add_dead_letter(body.email, body.step, body.error, body.payload)
        log.error("external failure recorded", extra={"step": body.step, "dead_letter_id": dl_id})
        return {"dead_letter_id": dl_id}

    @app.post("/dead-letters/{dl_id}/replay", dependencies=[Depends(check_secret)])
    def replay(dl_id: int) -> dict:
        try:
            return asdict(pl().replay(dl_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="dead letter not found") from None

    return app


