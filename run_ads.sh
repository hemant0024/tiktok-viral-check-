#!/usr/bin/env bash
# Competitor ads flow. The cron equivalent of workflows/n8n/ads.json.
#
# Run this at least 20 minutes after run_ugc.sh. Both write CONTENT_SNAPSHOTS,
# and overlapping runs double-write them, which corrupts the velocity history
# the whole viral signal is built on.
#
# No trends stage: trends are day-over-day view velocity, and Meta publishes no
# views for US commercial ads. Ads day-over-day is days_running and
# variation_count, already on the radar row.
set -uo pipefail
cd "$(dirname "$0")"
PY="${CI_PYTHON:-$HOME/.civenv/bin/python}"
export PYTHONPATH=src

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
run() { log "$1"; shift; "$PY" -m ci "$@" 2>&1 | tail -3; }

log "=== competitor ads, $(date -u +%F) ==="
run "collect competitor ads"  collect meta_ads
run "score ads"               radar --kind ads --json
run "push ads tabs"           sheets-push --kind ads
log "=== done ==="
