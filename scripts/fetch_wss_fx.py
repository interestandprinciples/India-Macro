#!/usr/bin/env python3
"""
Fetch RBI Weekly Statistical Supplement (WSS) Table 2: Foreign Exchange Reserves.
This adds the BREAKDOWN (FCA / Gold / SDRs / IMF) which is only in WSS, not in
the standard DBIE Excel extract.

WSS is published every Friday at 5:00 PM IST on RBI's website:
  https://www.rbi.org.in/Scripts/BS_ViewWSS.aspx
The mobile listing at https://m.rbi.org.in/scripts/WSSViewDetail.aspx?PARAM1=2&TYPE=Section
gives us the XLSX URLs (one per table per week).

The "as on" date in each WSS release is the PREVIOUS Friday — so a release on
2026-08-28 contains data as on 2026-08-21.

We keep the most recent ~10 weeks in the JSON; older releases can be fetched
on demand by running this with --weeks N.

Output: data/wss_fx_reserves.json with structure:
  {
    "generatedAt": "...",
    "source": "RBI Weekly Statistical Supplement (WSS) — Table 2",
    "latest_wss_release": "2026-08-28",
    "latest_as_on": "2026-08-21",
    "series_meta": { "1 Total Reserves": {...}, ... },
    "time_series": { "1 Total Reserves": [{"date":"...","value":...}, ...], ... }
  }
"""
from __future__ import annotations
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl required. pip install openpyxl", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
OUT = BASE_DIR / "data" / "wss_fx_reserves.json"
LOG = BASE_DIR / "data" / "wss_fx_reserves.log"

UA_DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
WSS_INDEX = "https://m.rbi.org.in/scripts/WSSViewDetail.aspx?PARAM1=2&TYPE=Section"  # Table 2 (FX Reserves)


def log(msg: str):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http_get(url: str, user_agent: str = UA_DESKTOP, retries: int = 4) -> bytes:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Referer": "https://www.rbi.org.in/Scripts/BS_ViewWSS.aspx",
                "Connection": "keep-alive",
            })
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=60) as r:
                data = r.read()
                # Handle gzip if the server sent it despite no Accept-Encoding
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                return data
        except Exception as e:
            last_err = e
            wait = 8 * (attempt + 1)
            log(f"  HTTP retry {attempt+1}/{retries} for {url[-60:]}: {e}; waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed after {retries} retries: {last_err}")


def find_wss_table2_urls(weeks: int = 12) -> list[tuple[str, str]]:
    """Scrape the mobile WSS page to get the last N weeks of Table 2 XLSX URLs.

    Returns list of (release_date_iso, url) sorted DESCENDING by date.
    """
    log(f"Fetching WSS index: {WSS_INDEX}")
    html = http_get(WSS_INDEX, user_agent=UA_MOBILE).decode("utf-8", errors="ignore")
    # Pattern: 2T_DDMMYYYYHASH.XLSX
    links = re.findall(
        r'href="(https://rbidocs\.rbi\.org\.in/rdocs/Wss/DOCs/2T_(\d{2})(\d{2})(\d{4})[A-F0-9]+\.XLSX)"',
        html, re.IGNORECASE
    )
    out = []
    for url, dd, mm, yyyy in links:
        try:
            dt = datetime(int(yyyy), int(mm), int(dd)).date()
        except ValueError:
            continue
        out.append((dt.isoformat(), url))
    out = sorted(set(out), key=lambda x: x[0], reverse=True)
    log(f"Found {len(out)} WSS Table 2 XLSX links in index; using latest {weeks}")
    return out[:weeks]


def is_footnote(label: str) -> bool:
    if not label:
        return False
    s = label.strip()
    if s.startswith("*") or s.startswith("#"):
        return True
    if any(x in s for x in ("Excludes", "Difference, if any", "currency swap")):
        return True
    return False


def parse_xlsx(data: bytes) -> dict | None:
    """Parse a WSS Table 2 XLSX. Returns {'as_on': 'YYYY-MM-DD', 'values': {...}}."""
    import io
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb["T_2"]
    rows = list(ws.iter_rows(values_only=True))

    # Find "as on" date in the header row
    ason_date = None
    for r in rows:
        if r and len(r) > 2 and r[1] == "Item" and isinstance(r[2], str) and "As on" in r[2]:
            ason_str = r[2].replace("As on", "").strip().rstrip(",")
            for fmt in ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y"):
                try:
                    ason_date = datetime.strptime(ason_str.replace(".", ""), fmt).date()
                    break
                except ValueError:
                    pass
            break
    if not ason_date:
        return None

    values = {}
    for r in rows:
        if not r or len(r) < 8:
            continue
        label = r[1]
        if not isinstance(label, str):
            continue
        label = label.strip()
        if not label or is_footnote(label):
            continue
        if label in ("Item", "2. Foreign Exchange Reserves*"):
            continue
        if any(x in label for x in ("As on", "Variation", "End-March")):
            continue
        if label in ("Week", "Year"):
            continue
        if label.startswith("₹") or label.startswith("US$"):
            continue
        if label.isdigit():
            continue
        inr_cr = r[2]
        usd_mn = r[3]
        try:
            inr_cr = float(inr_cr) if inr_cr not in (None, "-", "") else None
            usd_mn = float(usd_mn) if usd_mn not in (None, "-", "") else None
        except (ValueError, TypeError):
            continue
        if usd_mn is None and inr_cr is None:
            continue
        values[label] = {"inr_crore": inr_cr, "usd_million": usd_mn}
    return {"as_on": ason_date.isoformat(), "values": values}


def load_existing() -> dict:
    if OUT.exists():
        try:
            with OUT.open("r", encoding="utf-8") as f:
                d = json.load(f)
            if "time_series" in d:
                return d
        except Exception:
            pass
    return {
        "generatedAt": None,
        "source": "RBI Weekly Statistical Supplement (WSS) — Table 2: Foreign Exchange Reserves",
        "note": "Released every Friday at 5:00 PM IST; data is 'as on' the previous Friday",
        "latest_wss_release": None,
        "latest_as_on": None,
        "series_meta": {
            "1 Total Reserves": {"label": "Total Reserves", "unit": "US$ Million"},
            "1.1 Foreign Currency Assets #": {"label": "Foreign Currency Assets", "unit": "US$ Million"},
            "1.2 Gold": {"label": "Gold", "unit": "US$ Million"},
            "1.3 SDRs": {"label": "SDRs", "unit": "US$ Million"},
            "1.4 Reserve Position in the IMF": {"label": "Reserve Position in the IMF", "unit": "US$ Million"},
        },
        "time_series": {},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weeks", type=int, default=12, help="How many recent weeks to fetch (default 12)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    log(f"Starting WSS Table 2 fetch (last {args.weeks} weeks)")
    try:
        url_list = find_wss_table2_urls(weeks=args.weeks)
    except Exception as e:
        log(f"FAILED to find WSS URLs: {e}")
        return 1

    if not url_list:
        log("No WSS URLs found — aborting")
        return 1

    fresh = []
    for date_str, url in url_list:
        log(f"  Fetching WSS release {date_str} ...")
        try:
            data = http_get(url, user_agent=UA_DESKTOP)
        except Exception as e:
            log(f"    FAILED: {e}; skipping")
            continue
        rec = parse_xlsx(data)
        if not rec:
            log(f"    parse FAILED; skipping")
            continue
        rec["wss_release"] = date_str
        fresh.append(rec)
        log(f"    ✓ as on {rec['as_on']}: {len(rec['values'])} series")
        time.sleep(3)  # be polite

    if not fresh:
        log("No fresh WSS data parsed — keeping existing file unchanged")
        return 1

    # Merge with existing
    existing = load_existing()
    # Build a map: as_on -> {wss_release, values}
    merged: dict[str, dict] = {}
    for ts in existing.get("time_series", {}).values():
        for pt in ts:
            ason = pt["date"]
            if ason not in merged:
                # find wss_release from old records
                merged[ason] = {"wss_release": None, "values": {}}
    # We don't have wss_release per as_on in the old format, so look it up from raw records
    # For now, just preserve any existing as_on entries that we don't have new data for
    for rec in fresh:
        merged[rec["as_on"]] = {"wss_release": rec["wss_release"], "values": rec["values"]}

    # Build the new structure
    all_series = set()
    for rec in merged.values():
        all_series.update(rec["values"].keys())
    main_series = sorted([k for k in all_series if k.startswith(("1 ", "1.1", "1.2", "1.3", "1.4"))])

    out = dict(existing)
    out["generatedAt"] = datetime.now().isoformat() + "Z"
    out["latest_wss_release"] = max((r["wss_release"] for r in fresh if r.get("wss_release")), default=None)
    out["latest_as_on"] = max((r["as_on"] for r in fresh), default=None)
    out["time_series"] = {
        label: [
            {"date": ason, "wss_release": merged[ason]["wss_release"], "value": merged[ason]["values"][label]["usd_million"]}
            for ason in sorted(merged.keys())
            if label in merged[ason]["values"] and merged[ason]["values"][label]["usd_million"] is not None
        ]
        for label in main_series
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    log(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes); latest_as_on={out['latest_as_on']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
