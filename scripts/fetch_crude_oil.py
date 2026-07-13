#!/usr/bin/env python3
"""
Daily fetch: pull the Indian-basket crude oil price from PPAC
(https://ppac.gov.in/prices/international-prices-of-crude-oil) and
also grab ~5 years of Brent daily from Yahoo Finance as a long-term
trend proxy (Indian basket ≈ 70% Brent + 30% Oman/Dubai).

The PPAC site embeds a daily Excel file
(Crude_PP_1_a_InternationalPrice(C)_DD.MM.YYYY.xlsx) which contains:
  - The latest daily price as a footnote ("Crude Oil Indian Basket as
    on DD.MM.YYYY is $ XX.XX/bbl.")
  - Monthly averages for the current fiscal year (Apr-Mar)

We use Playwright (headless Chromium) to load the page, locate the
download link, then download the Excel directly.

Output
------
  data/crude_oil.json:
    {
      "generatedAt": "...",
      "source": "PPAC + Yahoo Finance",
      "latest": {"date": "2026-07-03", "price": 68.21, "unit": "USD/bbl"},
      "monthly": [{"year": "2026-27", "month": "Apr", "price": 114.48}, ...],
      "brent_daily": [{"date": "...", "price": ...}, ...],
      "metadata": {...}
    }
"""
from __future__ import annotations
import argparse
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
from datetime import datetime, timedelta
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
OUT = BASE_DIR / "data" / "crude_oil.json"
LOG = BASE_DIR / "data" / "crude_oil.log"

PAGE_URL = "https://ppac.gov.in/prices/international-prices-of-crude-oil"


def log(msg: str):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------- PPAC: latest + monthly ----------------------

def fetch_ppac_latest():
    """Returns (latest_date_iso, latest_price, monthly_prices_list).

    Uses Playwright to load the page (JS needs to execute to render the
    table), then extracts the daily "as on" price from the notes and
    the monthly averages from the table.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page()
        try:
            page.goto(PAGE_URL, timeout=45000, wait_until="networkidle")
            page.wait_for_timeout(4000)

            # Parse "as on" daily price from notes: "Crude Oil Indian Basket as on 03.07.2026 is $ 68.21/bbl."
            note_text = page.evaluate("document.getElementById('reportList')?.textContent || ''")
            m = re.search(r"as on (\d{2})\.(\d{2})\.(\d{4})\s+is\s+\$\s*([\d.]+)/bbl", note_text)
            if not m:
                raise RuntimeError(f"Could not parse 'as on' price from page notes")
            dd, mm, yyyy, price = m.group(1), m.group(2), m.group(3), float(m.group(4))
            latest_date_iso = f"{yyyy}-{mm}-{dd}"

            # Parse monthly averages from the first data row in #reportList
            # (format: row with year like "2026-27" and 12 month values)
            monthly = []
            rows = page.evaluate("""
              Array.from(document.querySelectorAll('#reportList tr')).map(r =>
                Array.from(r.querySelectorAll('td')).map(c => c.textContent.trim())
              )
            """)
            month_names = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
            for row in rows:
                if not row or len(row) < 13:
                    continue
                # First cell is the FY label (e.g. "2026-27")
                if re.match(r"^\d{4}-\d{2}$", row[0]):
                    fy = row[0]
                    for i, val in enumerate(row[1:13]):
                        if val and val.strip():
                            try:
                                monthly.append({
                                    "fy": fy,
                                    "month": month_names[i],
                                    "price": float(val),
                                })
                            except ValueError:
                                pass
            return latest_date_iso, price, monthly
        finally:
            browser.close()


# ---------------------- Yahoo: Brent daily history ----------------------

def fetch_brent_daily(years: int = 5):
    """Pull ~N years of Brent daily close from Yahoo Finance via yfinance."""
    import yfinance as yf
    t = yf.Ticker("BZ=F")
    h = t.history(period=f"{years}y", auto_adjust=False)
    if h is None or len(h) == 0:
        raise RuntimeError("no Brent history")
    closes = h["Close"].dropna()
    out = []
    for ts, v in closes.items():
        if hasattr(ts, "date"):
            iso = ts.date().isoformat()
        else:
            iso = str(ts)[:10]
        out.append({"date": iso, "price": float(v)})
    return out


# ---------------------- Persistence ----------------------

def load_existing():
    if not OUT.exists():
        return {"monthly": [], "brent_daily": [], "latest": None}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"monthly": [], "brent_daily": [], "latest": None}


def merge(existing: dict, latest: dict, monthly: list, brent: list) -> dict:
    out = existing
    out["latest"] = latest
    # Replace monthly (always current FY only)
    other_fy = [m for m in out.get("monthly", []) if m["fy"] != (latest and (monthly[0]["fy"] if monthly else None))]
    out["monthly"] = other_fy + monthly
    # Merge brent daily (dedupe by date)
    by_date = {r["date"]: r["price"] for r in out.get("brent_daily", [])}
    for r in brent:
        by_date[r["date"]] = r["price"]
    merged = [{"date": d, "price": by_date[d]} for d in sorted(by_date)]
    out["brent_daily"] = merged
    out["generatedAt"] = datetime.utcnow().isoformat() + "Z"
    out["source"] = "PPAC (ppac.gov.in) + Yahoo Finance (BZ=F)"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brent-years", type=int, default=5,
                    help="How many years of Brent history to fetch (default 5)")
    ap.add_argument("--no-brent", action="store_true",
                    help="Skip the Brent daily fetch (PPAC only)")
    args = ap.parse_args()

    existing = load_existing()
    log(f"Fetching crude oil: PPAC + Brent")

    # PPAC
    latest_date_iso, latest_price, monthly = fetch_ppac_latest()
    log(f"  PPAC latest: ${latest_price}/bbl as of {latest_date_iso}")
    log(f"  PPAC monthly: {len(monthly)} entries")

    latest = {"date": latest_date_iso, "price": latest_price, "unit": "USD/bbl"}

    # Brent
    brent = []
    if not args.no_brent:
        try:
            brent = fetch_brent_daily(years=args.brent_years)
            log(f"  Brent daily: {len(brent)} entries, latest {brent[-1]['date']} = ${brent[-1]['price']:.2f}")
        except Exception as e:
            log(f"  Brent fetch FAILED: {e}")

    merged = merge(existing, latest, monthly, brent)
    merged["metadata"] = {
        "name": "Crude Oil Indian Basket",
        "source_primary": "PPAC",
        "source_secondary": "Yahoo Finance Brent (BZ=F) — Indian basket ≈ 70% Brent + 30% Oman/Dubai",
        "unit": "USD/bbl",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    log(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())