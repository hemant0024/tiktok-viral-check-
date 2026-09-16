#!/usr/bin/env bash
# Superseded by run_ugc.sh + run_ads.sh, which run the two halves separately so
# one failing source cannot take the other down. Kept so an existing crontab does
# not silently stop working.
set -uo pipefail
cd "$(dirname "$0")"
echo "run_daily.sh is superseded. Running both flows in sequence."
./run_ugc.sh
sleep 5
./run_ads.sh
