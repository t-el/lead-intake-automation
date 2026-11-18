from fastapi.testclient import TestClient

from lead_intake.api import create_app
from lead_intake.pipeline import Pipeline


def client(settings):
    return TestClient(create_app(Pipeline(settings, sleep=lambda s: None)))


def test_health(settings):
    body = client(settings).get("/health").json()
    assert body["ok"] and body["ai"] == "heuristic" and body["sink"] == "sqlite"


def test_webhook_status_codes(settings, good_lead):
    c = client(settings)
    assert c.post("/webhook/lead", json=good_lead).status_code == 201
    assert c.post("/webhook/lead", json=good_lead).status_code == 200  # duplicate
    assert c.post("/webhook/lead", json={"email": "info@down-api.com", "name": "D"}).status_code == 202
    assert c.post("/webhook/lead", json={"email": "bad"}).status_code == 422
    assert len(c.get("/dead-letters").json()) == 2
    assert len(c.get("/leads").json()) == 1


def test_n8n_step_endpoints(settings, good_lead):
    c = client(settings)
    scored = c.post("/steps/enrich-score", json=good_lead).json()
    assert scored["duplicate"] is False and scored["score"]["tier"] == "hot"
    saved = c.post("/steps/save", json=scored).json()
    assert saved["saved"]
    assert c.post("/steps/enrich-score", json=good_lead).json()["duplicate"] is True


def test_external_failure_and_replay(settings, good_lead):
    c = client(settings)
    dl = c.post("/dead-letters", json={"step": "n8n:slack", "error": "boom", "payload": good_lead}).json()
    r = c.post(f"/dead-letters/{dl['dead_letter_id']}/replay").json()
    assert r["status"] == "processed"
    assert c.get("/dead-letters").json() == []
    assert c.post("/dead-letters/999/replay").status_code == 404


def test_webhook_secret(settings, monkeypatch, good_lead):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    c = client(settings)
    assert c.post("/webhook/lead", json=good_lead).status_code == 401
    assert c.post("/webhook/lead", json=good_lead, headers={"X-Webhook-Secret": "s3cret"}).status_code == 201


def test_step_endpoint_returns_503_on_transient_failure(settings):
    r = client(settings).post("/steps/enrich-score", json={"email": "info@down-api.com", "name": "D"})
    assert r.status_code == 503 and r.json()["retryable"] is True
