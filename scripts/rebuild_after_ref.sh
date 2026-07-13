#!/usr/bin/env bash
# Rebuild the dashboard after a ref-rates fetch.
# Called by com.user.rbi-macro-ref.plist on a daily schedule.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"
# Only rebuild if the ref rates file actually changed (vs yesterday)
REF="$ROOT/data/reference_rates.json"
if [[ ! -s "$REF" ]]; then exit 0; fi
python3 "$HERE/build_dashboard.py" --no-extract >> "$ROOT/data/launchd.ref.out.log" 2>&1
