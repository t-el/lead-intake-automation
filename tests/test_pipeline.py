import json

from lead_intake.sinks import CsvSink, SqliteSink


def test_happy_path_saves_and_alerts_hot_lead(pipeline, settings, good_lead):
    r = pipeline.process(good_lead)
    assert r.status == "processed" and r.tier == "hot"
    rows = SqliteSink(settings.data_dir / "crm.db").all()
    assert rows[0]["email"] == "sarah.chen@northwind-logistics.com"
    assert rows[0]["company"] == "Northwind Logistics"
    alerts = [json.loads(line) for line in (settings.data_dir / "alerts.log").read_text().splitlines()]
    assert alerts[-1]["title"].startswith("Hot lead")


def test_duplicate_email_is_skipped_case_insensitive(pipeline, good_lead):
    assert pipeline.process(good_lead).status == "processed"
    again = dict(good_lead, email=good_lead["email"].upper())
    assert pipeline.process(again).status == "duplicate"


def test_transient_enrichment_failure_is_retried(pipeline):
    r = pipeline.process({"email": "ops@flaky-co.com", "name": "Priya", "title": "COO"})
    assert r.status == "processed"
    assert pipeline.store.dead_letters() == []


def test_exhausted_retries_go_to_dead_letter_and_error_channel(pipeline, settings):
    r = pipeline.process({"email": "info@down-api.com", "name": "Down"})
    assert r.status == "dead_lettered" and r.dead_letter_id
    dl = pipeline.store.dead_letters()
    assert len(dl) == 1 and dl[0]["step"] == "enrich"
    assert dl[0]["payload"]["email"] == "info@down-api.com"
    log = (settings.data_dir / "alerts.log").read_text()
    assert "Lead pipeline failure" in log


def test_invalid_payload_is_dead_lettered_not_crashing(pipeline):
    r = pipeline.process({"email": "nope", "name": ""})
    assert r.status == "invalid"
    assert pipeline.store.dead_letters()[0]["step"] == "validate"


def test_sink_failure_dead_letters_and_replay_resolves(settings, good_lead):
    from lead_intake.pipeline import Pipeline
    from lead_intake.retry import TransientError

    class BrokenThenOk:
        name = "broken"
        ok = False

        def write(self, lead):
            if not self.ok:
                raise TransientError("CRM 503")
            return "crm:1"

    sink = BrokenThenOk()
    p = Pipeline(settings, sink=sink, sleep=lambda s: None)
    r = p.process(good_lead)
    assert r.status == "dead_lettered"
    assert p.store.dead_letters()[0]["step"] == "save"
    assert not p.store.is_processed("sarah.chen@northwind-logistics.com")

    sink.ok = True
    replayed = p.replay(r.dead_letter_id)
    assert replayed.status == "processed"
    assert p.store.dead_letters() == []


def test_csv_sink_is_idempotent(tmp_path, pipeline, good_lead):
    from lead_intake.models import Enrichment, LeadIn, ProcessedLead, Score

    sink = CsvSink(tmp_path / "out.csv")
    pl = ProcessedLead(lead=LeadIn(**good_lead), enrichment=Enrichment(domain="x.com"),
                       score=Score(score=50, tier="warm", summary="s", scored_by="heuristic"))
    sink.write(pl)
    assert sink.write(pl).endswith(":exists")
    assert len((tmp_path / "out.csv").read_text().strip().splitlines()) == 2


def test_alert_failure_does_not_lose_the_lead(settings, good_lead):
    from lead_intake.pipeline import Pipeline
    from lead_intake.retry import TransientError

    class DeadSlack:
        name = "slack"

        def send(self, *a, **k):
            raise TransientError("slack down")

    p = Pipeline(settings, notifier=DeadSlack(), sleep=lambda s: None)
    r = p.process(good_lead)
    assert r.status == "processed"
    assert p.store.dead_letters()[0]["step"] == "notify"
