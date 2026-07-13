# India Macroeconomic Dashboard — launchd jobs

The dashboard stays fresh via 6 launchd jobs that run at scheduled times throughout the trading day.

## Schedule

| Time (IST)   | Job                              | What it does                                                                                    |
| ------------ | -------------------------------- | ----------------------------------------------------------------------------------------------- |
| 14:30        | `com.user.rbi-macro-ref`         | Pulls daily RBI Reference Rate Archive (USD, GBP, EUR, JPY, AED, IDR)                           |
| **15:00**    | `com.user.rbi-macro-fetch`       | Pulls weekly + monthly DBIE macro indicators (50 indicators + others)                           |
| **15:45**    | `com.user.rbi-macro-refresh`     | **Master refresh** — runs ALL 5 sources in sequence + rebuilds dashboard with fresh embedded data |
| 17:00        | `com.user.rbi-macro-crude`       | Pulls PPAC Indian-basket crude oil + Brent daily historical                                       |
| every 15 min | `com.user.rbi-macro-live`        | Pulls live market tickers (USD/INR, NIFTY 50, Bank NIFTY, VIX, US 10Y, Gold, Brent)               |
| every 5 min  | `com.user.rbi-macro-watchdog`    | Restarts the live job if it ever stops (self-healing)                                            |

## What "Master refresh" (15:45) does

1. Fetch latest DBIE files (50 + Other Macroeconomic Indicators)
2. Fetch latest RBI Reference Rate Archive
3. Fetch latest PPAC Indian-basket crude + Brent daily
4. Fetch latest MoSPI / World Bank macro indicators (PLFS, GDP, IIP)
5. Fetch latest live market tickers
6. Rebuild the dashboard HTML with all fresh data inlined

## Install / manage

```bash
# Install all 6 jobs (idempotent — re-runs are safe)
bash scripts/install_launchd.sh install

# See current state
bash scripts/install_launchd.sh status

# Trigger an immediate refresh (no launchd required)
bash scripts/refresh_all.sh

# Uninstall all
bash scripts/install_launchd.sh uninstall
```

## Files

- `/tmp/rbi_*.sh` — actual scripts launchd runs (launchd can't access files under /Users/niravshah/.../RBI Macro Indicators/scripts/ with sufficient permissions, so we use a /tmp wrapper)
- `~/Library/LaunchAgents/com.user.rbi-macro-*.plist` — registered jobs
- `/tmp/launchd.*.out.log` — stdout/stderr for each job
- `data/fetch.log` — DBIE fetch history
- `data/launchd.live.out.log` — live ticker fetch history

## Troubleshooting

```bash
# Force a job to run now
launchctl kickstart -k gui/$(id -u)/com.user.rbi-macro-refresh

# Check job state
launchctl print gui/$(id -u)/com.user.rbi-macro-refresh

# See logs
tail -f /tmp/launchd.refresh.out.log
```

## Adding a new data source

1. Write `scripts/fetch_<name>.py` that writes to `data/<name>.json`
2. Add it to the list in `scripts/refresh_all.sh` (and `/tmp/rbi_refresh_all.sh`)
3. Embed the JSON via `scripts/build_dashboard.py` (already supports most common patterns)
4. Run `bash scripts/install_launchd.sh install` to re-register jobs
