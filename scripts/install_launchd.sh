#!/usr/bin/env bash
# Install / uninstall / inspect the launchd jobs that drive the dashboard.
#
#   ./scripts/install_launchd.sh install    # copy all plists to LaunchAgents and load them
#   ./scripts/install_launchd.sh uninstall  # unload and remove
#   ./scripts/install_launchd.sh status     # show current state
#   ./scripts/install_launchd.sh run        # trigger immediate DBIE fetch (for testing)

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

JOBS=(
  "com.user.rbi-macro-fetch:com.user.rbi-macro-fetch.plist"
  "com.user.rbi-macro-live:com.user.rbi-macro-live.plist"
  "com.user.rbi-macro-ref:com.user.rbi-macro-ref.plist"
  "com.user.rbi-macro-crude:com.user.rbi-macro-crude.plist"
  "com.user.rbi-macro-refresh:com.user.rbi-macro-refresh.plist"
  "com.user.rbi-macro-watchdog:com.user.rbi-macro-watchdog.plist"
)

usage() { echo "Usage: $0 {install|uninstall|status|run}"; exit 1; }

install() {
  mkdir -p "$HOME/Library/LaunchAgents"
  for entry in "${JOBS[@]}"; do
    LABEL="${entry%%:*}"
    SRC="$HERE/${entry##*:}"
    DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
    if [[ ! -f "$SRC" ]]; then
      echo "skip: $SRC not found"
      continue
    fi
    cp "$SRC" "$DST"
    launchctl unload "$DST" 2>/dev/null || true
    launchctl load "$DST"
    echo "Installed: $DST"
    launchctl list | grep "$LABEL" || echo "(load may take a moment)"
  done
}

uninstall() {
  for entry in "${JOBS[@]}"; do
    LABEL="${entry%%:*}"
    DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
    launchctl unload "$DST" 2>/dev/null || true
    rm -f "$DST"
    echo "Removed $DST"
  done
}

status() {
  for entry in "${JOBS[@]}"; do
    LABEL="${entry%%:*}"
    if launchctl list | grep -q "$LABEL\b"; then
      echo "Status ($LABEL): loaded"
      launchctl list | grep "$LABEL"
    else
      echo "Status ($LABEL): not loaded"
    fi
  done
}

run() {
  python3 "$HERE/fetch_and_update.py"
}

case "${1:-}" in
  install)   install ;;
  uninstall) uninstall ;;
  status)    status ;;
  run)       run ;;
  *)         usage ;;
esac