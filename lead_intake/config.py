"""Settings loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional: load .env when python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))
    # Enrichment
    enrichment_mode: str = field(default_factory=lambda: os.getenv("ENRICHMENT_MODE", "mock"))  # mock | http
    enrichment_url: str = field(default_factory=lambda: os.getenv("ENRICHMENT_URL", ""))
    enrichment_api_key: str = field(default_factory=lambda: os.getenv("ENRICHMENT_API_KEY", ""))
    # AI scoring (any OpenAI-compatible endpoint). Empty key => deterministic heuristic scorer.
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    hot_threshold: int = field(default_factory=lambda: int(os.getenv("HOT_LEAD_THRESHOLD", "70")))
    # Destination
    sink: str = field(default_factory=lambda: os.getenv("SINK", "sqlite"))  # sqlite | csv | google_sheets | hubspot
    google_sheets_webhook_url: str = field(default_factory=lambda: os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", ""))
    hubspot_token: str = field(default_factory=lambda: os.getenv("HUBSPOT_TOKEN", ""))
    # Alerts
    notifier: str = field(default_factory=lambda: os.getenv("NOTIFIER", "console"))  # console | slack | email
    slack_webhook_url: str = field(default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL", ""))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    alert_email_to: str = field(default_factory=lambda: os.getenv("ALERT_EMAIL_TO", ""))
    # Reliability
    retry_attempts: int = field(default_factory=lambda: int(os.getenv("RETRY_ATTEMPTS", "4")))
    retry_base_delay: float = field(default_factory=lambda: float(os.getenv("RETRY_BASE_DELAY", "0.5")))
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", ""))
    log_json: bool = field(default_factory=lambda: _bool("LOG_JSON", True))

    @property
    def state_db(self) -> Path:
        return self.data_dir / "state.db"


def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
