#!/usr/bin/env bash
# Rebuild the dashboard after a crude oil fetch.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"
python3 "$HERE/fetch_crude_oil.py" >> "$ROOT/data/launchd.crude.out.log" 2>&1
python3 "$HERE/build_dashboard.py" --no-extract >> "$ROOT/data/launchd.crude.out.log" 2>&1
