"""The pure-Python pipeline: validate -> dedupe -> enrich -> score -> save -> alert.

Every external step is wrapped in retry_call. Anything that still fails lands in the
dead-letter queue with the original payload, and the error channel is notified, so no
lead is ever silently lost.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import ValidationError

from .config import Settings
from .enrich import build_enricher
from .models import Enrichment, LeadIn, ProcessedLead, Score
from .notify import build_notifier
from .retry import retry_call
from .scoring import Scorer
from .sinks import build_sink
from .store import StateStore

log = logging.getLogger("lead_intake.pipeline")


@dataclass
class Result:
    status: str  # processed | duplicate | dead_lettered | invalid
    email: Optional[str] = None
    score: Optional[int] = None
    tier: Optional[str] = None
    sink_ref: Optional[str] = None
    dead_letter_id: Optional[int] = None
    error: Optional[str] = None
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)


class Pipeline:
    def __init__(self, settings: Settings, *, enricher=None, scorer=None, sink=None, notifier=None,
                 store: StateStore | None = None, sleep: Callable[[float], None] = time.sleep):
        self.s = settings
        self.enricher = enricher or build_enricher(settings)
        self.scorer = scorer or Scorer(settings)
        self.sink = sink or build_sink(settings)
        self.notifier = notifier or build_notifier(settings)
        self.store = store or StateStore(settings.state_db)
        self.sleep = sleep

    def _retry(self, fn, step: str):
        return retry_call(fn, attempts=self.s.retry_attempts, base_delay=self.s.retry_base_delay,
                          step=step, sleep=self.sleep)

    # -- reusable steps (also exposed to n8n as HTTP endpoints) ---------------
    def enrich_and_score(self, lead: LeadIn) -> tuple[Enrichment, Score]:
        enrichment = self._retry(lambda: self.enricher.enrich(lead.email), "enrich")
        score = self.scorer.score(lead, enrichment)
        return enrichment, score

    def save(self, processed: ProcessedLead) -> str:
        ref = self._retry(lambda: self.sink.write(processed), "save")
        self.store.mark_processed(processed.lead.email, ref, processed.score.score, processed.score.tier)
        return ref

    def alert_hot(self, processed: ProcessedLead) -> None:
        sc = processed.score
        text = (f"{sc.summary}\nScore: {sc.score}/100 ({sc.scored_by})\nWhy: {', '.join(sc.reasons)}\n"
                f"Email: {processed.lead.email}\nMessage: {processed.lead.message or '-'}")
        self._retry(lambda: self.notifier.send(f"Hot lead: {processed.lead.name}", text, "info"), "notify")

    def _dead_letter(self, payload: dict, email: Optional[str], step: str, exc: Exception) -> int:
        dl_id = self.store.add_dead_letter(email, step, f"{type(exc).__name__}: {exc}", payload)
        log.error("lead moved to dead-letter queue",
                  extra={"email": email, "step": step, "dead_letter_id": dl_id, "error": str(exc)})
        try:
            self.notifier.send("Lead pipeline failure",
                               f"Step '{step}' failed for {email or 'unknown'}: {exc}\nDead-letter id: {dl_id}",
                               "error")
        except Exception:  # noqa: BLE001 - error channel itself failing must not crash the pipeline
            log.exception("error channel unavailable")
        return dl_id

    # -- full run ------------------------------------------------------------
    def process(self, payload: dict) -> Result:
        started = time.perf_counter()
        ms = lambda: int((time.perf_counter() - started) * 1000)  # noqa: E731
        try:
            lead = LeadIn.model_validate(payload)
        except ValidationError as exc:
            err = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            dl = self._dead_letter(payload, payload.get("email"), "validate", ValueError(err))
            return Result("invalid", email=payload.get("email"), error=err, dead_letter_id=dl, duration_ms=ms())

        if self.store.is_processed(lead.email):
            log.info("duplicate lead skipped", extra={"email": lead.email})
            return Result("duplicate", email=lead.email, duration_ms=ms())

        step = "enrich"
        try:
            enrichment, score = self.enrich_and_score(lead)
            processed = ProcessedLead(lead=lead, enrichment=enrichment, score=score)
            step = "save"
            ref = self.save(processed)
        except Exception as exc:  # noqa: BLE001
            dl = self._dead_letter(payload, lead.email, step, exc)
            return Result("dead_lettered", email=lead.email, error=str(exc), dead_letter_id=dl, duration_ms=ms())

        if score.tier == "hot":
            try:
                self.alert_hot(processed)
            except Exception as exc:  # noqa: BLE001 - the lead is saved; only the alert is queued for retry
                self._dead_letter(payload, lead.email, "notify", exc)

        log.info("lead processed", extra={"email": lead.email, "score": score.score, "tier": score.tier,
                                          "scored_by": score.scored_by, "sink_ref": ref, "duration_ms": ms()})
        return Result("processed", email=lead.email, score=score.score, tier=score.tier, sink_ref=ref,
                      duration_ms=ms(), details={"summary": score.summary, "reasons": score.reasons})

    def replay(self, dead_letter_id: int) -> Result:
        dl = self.store.get_dead_letter(dead_letter_id)
        if dl is None:
            raise KeyError(dead_letter_id)
        result = self.process(dl["payload"])
        # Success resolves the entry. A new failure creates a fresh entry with the latest error,
        # so the old one is closed as superseded (the queue never shows the same lead twice).
        self.store.resolve_dead_letter(dead_letter_id)
        return result
