"""Alerts for hot leads and the error channel. Console (mock) by default; Slack or email in production."""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import httpx

from .config import Settings
from .retry import TransientError, classify_http_status

log = logging.getLogger("lead_intake.notify")


class ConsoleNotifier:
    """Mock notifier: logs the alert and appends it to data/alerts.log so you can inspect it."""

    name = "console"

    def __init__(self, path: Path):
        self.path = path

    def send(self, title: str, text: str, level: str = "info") -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "title": title, "text": text}
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        log.info("alert sent", extra={"channel": "console", "title": title, "level": level})


class SlackNotifier:
    name = "slack"

    def __init__(self, webhook_url: str, client: httpx.Client | None = None):
        if not webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL is required when NOTIFIER=slack")
        self.url = webhook_url
        self.client = client or httpx.Client(timeout=10.0)

    def send(self, title: str, text: str, level: str = "info") -> None:
        emoji = {"info": ":fire:", "error": ":rotating_light:"}.get(level, ":bell:")
        try:
            resp = self.client.post(self.url, json={"text": f"{emoji} *{title}*\n{text}"})
        except httpx.TransportError as exc:
            raise TransientError(f"slack transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise classify_http_status(resp.status_code)(f"slack HTTP {resp.status_code}")


class EmailNotifier:
    name = "email"

    def __init__(self, s: Settings):
        if not (s.smtp_host and s.alert_email_to):
            raise ValueError("SMTP_HOST and ALERT_EMAIL_TO are required when NOTIFIER=email")
        self.s = s

    def send(self, title: str, text: str, level: str = "info") -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[{level.upper()}] {title}"
        msg["From"] = self.s.smtp_user or "lead-bot@localhost"
        msg["To"] = self.s.alert_email_to
        msg.set_content(text)
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPServerDisconnected) as exc:
            raise TransientError(f"smtp error: {exc}") from exc


def build_notifier(s: Settings):
    if s.notifier == "slack":
        return SlackNotifier(s.slack_webhook_url)
    if s.notifier == "email":
        return EmailNotifier(s)
    return ConsoleNotifier(s.data_dir / "alerts.log")
