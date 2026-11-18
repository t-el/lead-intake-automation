#!/usr/bin/env bash
# End-to-end demo in mock mode (no API keys, no network): batch run, dedupe, retries, DLQ, replay, API.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
export DATA_DIR=${DATA_DIR:-data/demo} LOG_JSON=${LOG_JSON:-false} RETRY_BASE_DELAY=${RETRY_BASE_DELAY:-0.2}
rm -rf "$DATA_DIR" && mkdir -p "$DATA_DIR"

echo "### 1. Pure-Python pipeline on 8 sample leads (incl. duplicate, flaky API, dead API, invalid)"
$PY -m lead_intake.cli process samples/leads.json

echo; echo "### 2. Dead-letter queue"
$PY -m lead_intake.cli dlq

echo; echo "### 3. Local CRM table (data in $DATA_DIR/crm.db)"
$PY - <<PY
from lead_intake.sinks import SqliteSink
for r in SqliteSink("$DATA_DIR/crm.db").all():
    print(f"  {r['score']:>3}  {r['tier']:<5} {r['email']:<36} {r['company']}")
PY

echo; echo "### 4. Alerts sent (mock Slack/email -> $DATA_DIR/alerts.log)"
cut -c1-160 "$DATA_DIR/alerts.log"

echo; echo "### 5. HTTP API (FastAPI webhook)"
PORT=${PORT:-8765}
$PY -m uvicorn --factory lead_intake.api:create_app --port "$PORT" --log-level warning &
PID=$!; trap 'kill $PID 2>/dev/null' EXIT
for _ in $(seq 1 40); do curl -sf "localhost:$PORT/health" >/dev/null && break; sleep 0.25; done
curl -s "localhost:$PORT/health"; echo
curl -s -X POST "localhost:$PORT/webhook/lead" -H 'content-type: application/json' \
  -d '{"email":"mia@lumen-legal.de","name":"Mia Vogel","title":"Managing Partner","budget":"$6,000","message":"Automate client intake, budget approved"}' \
  -w '\n  -> HTTP %{http_code}\n'
curl -s -X POST "localhost:$PORT/webhook/lead" -H 'content-type: application/json' \
  -d '{"email":"mia@lumen-legal.de","name":"Mia Vogel"}' -w '\n  -> HTTP %{http_code} (duplicate)\n'
echo; echo "Demo complete."
