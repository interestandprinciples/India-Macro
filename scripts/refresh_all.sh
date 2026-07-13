#!/usr/bin/env bash
# Refresh the entire dashboard from all configured data sources and rebuild.
#
# Sources refreshed in this order:
#   1) DBIE (RBI macro indicators)         — fetch_and_update.py
#   2) RBI Reference Rate Archive           — fetch_reference_rates.py
#   3) PPAC Indian-basket crude oil         — fetch_crude_oil.py
#   4) World Bank / MoSPI-harmonized        — fetch_mospi_wb.py
#   5) Live market tickers (USD/INR, NIFTY) — fetch_live.py
#   6) Rebuild dashboard HTML                — build_dashboard.py --no-extract
#
# Usage:  bash scripts/refresh_all.sh
#
# Each step is non-fatal — a failure in live tickers (e.g. yfinance rate limit)
# should NOT prevent the dashboard from being rebuilt with whatever data we have.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"
mkdir -p data

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }
log() { echo "[$(ts)] $*"; }

ok_count=0
fail_count=0
declare -a FAILED_STEPS=()

run_step() {
  local label="$1"
  local script="$2"
  log "=== $label ==="
  if python3 "$HERE/$script" 2>&1; then
    log "  ✓ $label OK"
    ok_count=$((ok_count + 1))
  else
    log "  ✗ $label FAILED (continuing)"
    FAILED_STEPS+=("$label")
    fail_count=$((fail_count + 1))
  fi
}

run_step "DBIE"            "fetch_and_update.py"
run_step "RBI Reference Rates" "fetch_reference_rates.py"
run_step "PPAC Crude Oil"  "fetch_crude_oil.py"
run_step "MoSPI / World Bank" "fetch_mospi_wb.py"
run_step "Live tickers"    "fetch_live.py"

log "=== Rebuilding dashboard ==="
if python3 "$HERE/build_dashboard.py" --no-extract 2>&1; then
  log "  ✓ Dashboard rebuilt"
  ok_count=$((ok_count + 1))
else
  log "  ✗ Dashboard build FAILED"
  FAILED_STEPS+=("Rebuild dashboard")
  fail_count=$((fail_count + 1))
fi

log "========================================"
log "Done. $ok_count step(s) succeeded, $fail_count failed."
if [ $fail_count -gt 0 ]; then
  log "Failed: ${FAILED_STEPS[*]}"
  # Still exit 0 so the workflow completes — partial data is better than no data
  exit 0
fi
log "========================================"
