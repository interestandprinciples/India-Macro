#!/usr/bin/env bash
# Fetch live rates then rebuild the dashboard so the embedded snapshot
# is fresh and the live_rates.js wrapper gets re-generated.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"
python3 "$HERE/fetch_live.py" >> "$ROOT/data/launchd.live.out.log" 2>&1
python3 "$HERE/build_dashboard.py" --no-extract >> "$ROOT/data/launchd.live.out.log" 2>&1
