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
. tools/_venv.sh
ci_venv_ready

if ! "$PY" -c "import yaml, pydantic" >/dev/null 2>&1; then
  echo "Installing dependencies (first run only)"
  "$PIP" install -q --upgrade pip
  "$PIP" install -q -e . 2>/dev/null || "$PIP" install -q -r requirements.txt
fi

export PYTHONPATH="$PWD/src"
URL="http://127.0.0.1:$PORT"
( sleep 2; command -v open >/dev/null && open "$URL" ) &
exec "$PY" -m ci dashboard --port "$PORT"
