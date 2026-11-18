import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lead_intake.config import Settings  # noqa: E402
from lead_intake.pipeline import Pipeline  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("OPENAI_API_KEY", "WEBHOOK_SECRET", "SINK", "NOTIFIER", "ENRICHMENT_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_JSON", "false")
    s = Settings()
    s.retry_base_delay = 0.0
    return s


@pytest.fixture
def pipeline(settings):
    return Pipeline(settings, sleep=lambda _s: None)


@pytest.fixture
def good_lead():
    return {"email": "Sarah.Chen@northwind-logistics.com", "name": "Sarah Chen", "title": "Head of Operations",
            "budget": "$8,000", "message": "Need to automate our Shopify to WMS sync ASAP."}
