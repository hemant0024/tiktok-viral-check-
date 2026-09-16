#!/usr/bin/env bash
# Organic UGC flow. The cron equivalent of workflows/n8n/ugc.json.
# Ends at the sheet. No Claude step here — that node lives in the n8n graph.
set -uo pipefail
cd "$(dirname "$0")"
PY="${CI_PYTHON:-$HOME/.civenv/bin/python}"
export PYTHONPATH=src

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
run() { log "$1"; shift; "$PY" -m ci "$@" 2>&1 | tail -3; }

log "=== competitor UGC, $(date -u +%F) ==="
run "collect competitor UGC"  collect competitor_ugc
run "score UGC"               radar --kind ugc --json
run "day over day trends"     trends
run "push UGC tabs"           sheets-push --kind ugc
run "send to slack"           notify-radar slack
log "=== done ==="
