#!/usr/bin/env bash
# Every 30 minutes. Re-polls videos that look like they are taking off.
# Distribution waves need hourly readings; a daily snapshot cannot see them.
set -uo pipefail
cd "$(dirname "$0")"
PY="${CI_PYTHON:-$HOME/.civenv/bin/python}"
PYTHONPATH=src "$PY" -m ci watch 2>&1 | tail -3
