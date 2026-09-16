#!/usr/bin/env bash
# Starts the radar dashboard. Run it from anywhere:  ./dashboard.sh
#
# This exists because "python -m ci dashboard" needs PYTHONPATH pointing at src
# and there is no installed console script. Without it the command fails with
# "No module named ci", or picks up a different interpreter with none of the
# dependencies, which looks exactly like a dashboard with no data in it.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8787}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Making a virtual environment in $VENV (first run only)"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e . 2>/dev/null || "$VENV/bin/pip" install -q -r requirements.txt
fi

export PYTHONPATH="$PWD/src"
URL="http://127.0.0.1:$PORT"
( sleep 2; command -v open >/dev/null && open "$URL" ) &
exec "$VENV/bin/python" -m ci dashboard --port "$PORT"
