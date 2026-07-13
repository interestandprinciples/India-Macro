#!/usr/bin/env bash
# Master refresh script — runs all data sources in sequence and rebuilds
# the dashboard. Triggered by com.user.rbi-macro-refresh.plist at 15:45 IST.
# Uses absolute paths to avoid the launchd cwd "Operation not permitted" issue.
set -e
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
ROOT="/Users/niravshah/Desktop/RBI Macro Indicators"
LOG="/tmp/launchd.refresh.out.log"

# Use subshell to handle cwd without affecting caller
(
  cd "$ROOT" || { echo "Cannot cd to $ROOT" >> "$LOG"; exit 1; }
  echo "=== refresh started $(date) ===" >> "$LOG"
  python3 "$ROOT/scripts/fetch_and_update.py"        >> "$LOG" 2>&1 || echo "  DBIE failed" >> "$LOG"
  python3 "$ROOT/scripts/fetch_reference_rates.py"  >> "$LOG" 2>&1 || echo "  Ref failed" >> "$LOG"
  python3 "$ROOT/scripts/fetch_crude_oil.py"        >> "$LOG" 2>&1 || echo "  Crude failed" >> "$LOG"
  python3 "$ROOT/scripts/fetch_mospi_wb.py"         >> "$LOG" 2>&1 || echo "  MoSPI failed" >> "$LOG"
  python3 "$ROOT/scripts/fetch_live.py"             >> "$LOG" 2>&1 || echo "  Live failed" >> "$LOG"
  python3 "$ROOT/scripts/build_dashboard.py" --no-extract >> "$LOG" 2>&1 || echo "  Build failed" >> "$LOG"
  echo "=== refresh done $(date) ===" >> "$LOG"
)
