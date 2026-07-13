# India Macroeconomic Dashboard

A self-contained, interactive dashboard for **Indian macroeconomic indicators**
covering monetary policy, inflation, currency, banking, BoP, external debt, equity
markets, and more. Auto-refreshed daily at **15:45 IST** from public sources.

## What you get

- 📊 **156 series** across 13 themes (Monetary, Inflation, FX, BoP, Banking, …)
- 📈 **YoY / MoM / Trend overlays** on every chart
- 📌 **Latest Reads** strip with one-click pinning
- 🔍 **Smart search** (C‑P‑I → Consumer Price Index) with synonym expansion
- 🌓 **Light & dark mode** (auto-detects OS preference, persists in localStorage)
- 📱 **Mobile-first** — full bottom nav, swipeable Latest Reads, drawer with all
  filters
- 💾 **Self-contained** — the entire dashboard is a single HTML file with all
  data inlined; no server required

## Sources

| Source | Frequency | What's pulled |
|---|---|---|
| DBIE (`data.rbi.org.in`) | Weekly + Monthly | 50 Macroeconomic Indicators + Other Macroeconomic Indicators (156 series, ~50,762 data points) |
| RBI Reference Rate Archive | Daily | USD, GBP, EUR, JPY, AED, IDR |
| PPAC | Daily | Indian-basket crude oil price + Brent historical |
| MoSPI / World Bank | Annual | GDP per capita, GDP growth, IIP, PLFS unemployment, LFPR |
| Yahoo Finance | Real-time | USD/INR, NIFTY 50, NIFTY Bank, VIX, US 10Y, Gold, Brent |
| eSankhyiki / forex-feed | Real-time | USD/INR fallback |

## Quick start

```bash
# 1. Install Python dependencies
pip install pypdf openpyxl yfinance requests

# 2. Pull the latest data
bash scripts/refresh_all.sh

# 3. Open the dashboard
open dashboard/index.html
```

The HTML is self-contained — you can also just double-click `dashboard/index.html`.

## Daily auto-refresh

Two options for keeping data fresh:

### Option 1 — Local launchd (your Mac)

Already set up if you ran `install_launchd.sh install`. Schedule:

| Time (IST) | Job | What it does |
|---|---|---|
| 14:30 | `com.user.rbi-macro-ref` | RBI Reference Rate Archive (6 currencies) |
| 15:00 | `com.user.rbi-macro-fetch` | DBIE weekly + monthly |
| **15:45** | **`com.user.rbi-macro-refresh`** | **MASTER refresh** — all 5 sources + dashboard rebuild |
| 17:00 | `com.user.rbi-macro-crude` | PPAC crude + Brent |
| every 15 min | `com.user.rbi-macro-live` | Live market tickers |
| every 5 min | `com.user.rbi-macro-watchdog` | Self-heals the live job |

### Option 2 — GitHub Actions (free, runs even when Mac is off)

The included `.github/workflows/daily-refresh.yml` runs at **10:15 UTC = 3:45 PM IST**
on Mon–Fri:

1. Fetches all 5 data sources
2. Rebuilds the dashboard HTML
3. Publishes to **GitHub Pages** (or your custom domain)

This is what makes the dashboard publicly accessible at `interestandprinciples.com`
without depending on your Mac being on.

## Project layout

```
.
├── .github/
│   └── workflows/
│       └── daily-refresh.yml    ← GitHub Actions: 3:45 PM IST refresh
├── dashboard/
│   ├── index.html               ← the dashboard (built, ~3 MB)
│   └── curate.html              ← curation UI
├── data/
│   ├── macro_data.json          ← extracted DBIE dataset
│   ├── live_rates.json          ← live market tickers
│   ├── reference_rates.json     ← RBI reference rates
│   ├── crude_oil.json           ← PPAC crude oil
│   ├── mospi_wb.json            ← MoSPI / World Bank
│   ├── curation.json            ← user-curation rules
│   └── live_tickers.json        ← ticker config
├── scripts/
│   ├── extract_data.py
│   ├── build_dashboard.py
│   ├── fetch_and_update.py
│   ├── fetch_reference_rates.py
│   ├── fetch_crude_oil.py
│   ├── fetch_mospi_wb.py
│   ├── fetch_live.py
│   ├── refresh_all.sh           ← runs all 5 fetchers + rebuild
│   └── install_launchd.sh       ← macOS auto-refresh helper
└── 50 Macroeconomic Indicators.xlsx
└── Other Macroeconomic Indicators.xlsx
```

## Curation

Open `dashboard/curate.html` to:
- Hide any series from the grid
- Change each series' view mode (Level / YoY / MoM / Both / Trend)
- Pin series to the **Latest Reads** strip
- Apply bulk actions per theme

Click **💾 Save & rebuild** to download the updated `curation.json` —
drop it in `data/` and re-run `bash scripts/apply_curation.py` (or just
wait for the next auto-refresh).

## Deployment to a custom domain (interestandprinciples.com)

1. **Create a GitHub repo** from this project
2. **Enable GitHub Pages** in repo Settings → Pages → Source: GitHub Actions
3. **Add custom domain** in Pages settings: `interestandprinciples.com/india-macro`
4. **Update DNS** at your registrar: CNAME `india-macro.interestandprinciples.com`
   to `<your-username>.github.io`
5. **Enable HTTPS** in Pages settings

The `daily-refresh.yml` workflow automatically:
- Refreshes data at 3:45 PM IST every day
- Publishes the new `dashboard/index.html` to your GitHub Pages site

## License

MIT — feel free to fork, modify, and use.
