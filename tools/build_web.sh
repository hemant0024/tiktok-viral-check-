#!/usr/bin/env bash
# Builds the static site that goes to Vercel. Everything is frozen into one file.
set -euo pipefail
cd "$(dirname "$0")/.."
. tools/_venv.sh
ci_venv_ready
ci_project_deps

echo "baking"
PYTHONPATH=src "$PY" tools/bake_dashboard.py
mkdir -p web
cp radar-dashboard.html web/index.html
BYTES=$(wc -c < web/index.html | tr -d ' ')
echo "  web/index.html  $((BYTES/1024)) KB"
echo
echo "Deploy it:"
echo "  npx vercel --prod"
echo
echo "First run asks you to log in and names the project. After that the same"
echo "command redeploys. vercel.json already points at web/ with no build step."
