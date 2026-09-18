#!/usr/bin/env bash
# Builds the static site that goes to Vercel. Everything is frozen into one file.
set -euo pipefail
cd "$(dirname "$0")/.."
. tools/_venv.sh
ci_venv_ready

echo "baking"
PYTHONPATH=src "$PY" tools/bake_dashboard.py
mkdir -p web
cp radar-dashboard.html web/index.html
BYTES=$(wc -c < web/index.html | tr -d ' ')
echo "  web/index.html  $((BYTES/1024)) KB"
echo
echo "Deploy with:  vercel --prod  (or ask Claude to deploy it)"
