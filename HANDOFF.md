# Handoff: Lead Intake Automation

This is for whoever runs this system after delivery.

## What it does, in one line
Takes leads from a form webhook, enriches and scores them, saves them to the configured destination, alerts on hot leads, and parks every failure in a dead-letter queue (DLQ) that can be replayed.

## Where things live

| Thing | Location |
|---|---|
| Configuration | `.env` (template: `.env.example`) |
| Processing state (dedupe ledger + DLQ) | `data/state.db` (SQLite) |
| Local CRM table (when `SINK=sqlite`) | `data/crm.db`, table `leads` |
| CSV output (when `SINK=csv`) | `data/leads.csv` |
| Mock alerts (when `NOTIFIER=console`) | `data/alerts.log` |
| n8n workflow | `n8n/lead-intake-workflow.json` |
| Logs | stdout, one JSON object per line (`docker compose logs -f lead-api`) |

## Daily operation

- **Health:** `GET /health` returns the active sink, notifier and AI mode.
- **Check for failures:** `GET /dead-letters` or `python -m lead_intake.cli dlq`. An empty list is healthy.
- **Fix and replay:** once the cause is fixed (API key renewed, CRM back up), run `POST /dead-letters/{id}/replay` or `python -m lead_intake.cli replay <id>`. A successful replay resolves the entry. A failed replay closes it and opens a fresh entry with the new error.
- **Recent leads:** `GET /leads`.

## Common failures and what to do

| Symptom (log `msg` / DLQ `step`) | Likely cause | Action |
|---|---|---|
| `step=enrich`, HTTP 401/403 | Enrichment API key expired | Update `ENRICHMENT_API_KEY`, restart, replay |
| `step=save`, `hubspot HTTP 401` | HubSpot private-app token revoked | Create a new token with `crm.objects.contacts.write`, update `HUBSPOT_TOKEN`, replay |
| `step=save`, `sheets HTTP 302/401` | Apps Script redeployed or access changed | Redeploy as web app ("Anyone with the link") and update the URL |
| `LLM scoring failed, using heuristic fallback` | OpenAI quota or outage | No action needed, leads keep flowing on heuristic scores. Fix billing when convenient |
| `step=notify` | Slack webhook revoked | Create a new incoming webhook and update `SLACK_WEBHOOK_URL`. The lead itself was already saved |
| `step=validate` | Form sent unexpected fields | Check the payload in the DLQ and adjust the form mapping |

## Changing behaviour safely

- **Scoring rules:** `lead_intake/scoring.py` → `heuristic_score`. The hot threshold is `HOT_LEAD_THRESHOLD`.
- **LLM prompt:** `SYSTEM_PROMPT` in `scoring.py`. Keep the JSON-only contract.
- **New destination:** add a class with `name` and `write(lead) -> str` in `lead_intake/sinks/`, register it in `sinks/__init__.py`, and make `write` idempotent.
- **Retries:** `RETRY_ATTEMPTS` and `RETRY_BASE_DELAY` (seconds, exponential, with jitter).
- Run `pytest` before deploying. All 24 tests run offline in under a second.

## Security notes
- Secrets live only in `.env`, which is git-ignored. Never commit it.
- Set `WEBHOOK_SECRET` in production and send it as the `X-Webhook-Secret` header from the form or n8n.
- Lead data includes personal data (name, email). Keep `data/` on an encrypted volume and set a retention policy if you are under GDPR or Morocco's Law 09-08.

## Backups
`data/state.db` and `data/crm.db` are plain SQLite files. Back them up with `sqlite3 data/state.db ".backup backup.db"` or a volume snapshot.
