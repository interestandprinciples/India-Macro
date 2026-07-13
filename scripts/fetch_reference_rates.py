#!/usr/bin/env python3
"""
Daily fetch: download the RBI Reference Rate Archive for ALL currencies
(USD, GBP, EUR, JPY, AED, IDR) and append to a long-running historical JSON.

Source: https://www.rbi.org.in/scripts/referenceratearchive.aspx
This is an ASP.NET WebForms page — we GET it first to capture __VIEWSTATE
+ cookies, then POST with the form fields for each currency and date range.

Output
------
  data/reference_rates.json:
    {
      "generatedAt": "2026-07-06T10:30:00Z",
      "source": "RBI Reference Rate Archive",
      "currencies": ["USD","GBP","EUR","JPY","AED","IDR"],
      "rates": {
        "USD": [{"date":"2024-01-02","rate":83.20}, ...],
        "GBP": [...],
        ...
      }
    }

Usage
-----
  python3 scripts/fetch_reference_rates.py            # backfill last 30 days
  python3 scripts/fetch_reference_rates.py --days 365 # backfill 1 year
  python3 scripts/fetch_reference_rates.py --today    # fetch only today
"""
from __future__ import annotations
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
OUT = BASE_DIR / "data" / "reference_rates.json"
LOG = BASE_DIR / "data" / "reference_rates.log"

CURRENCIES = ["USD", "GBP", "EUR", "JPY", "AED", "IDR"]
# RBI quotes these rates as INR per N units of foreign currency.
# USD/GBP/EUR/AED are per 1, JPY is per 100, IDR is per 10000.
# We preserve RBI's convention (per N) but also store a "per1" normalized version
# for the dashboard, so all charts are on a comparable axis if needed.
UNITS_PER = {"USD": 1, "GBP": 1, "EUR": 1, "JPY": 100, "AED": 1, "IDR": 10000}
NAMES = {
    "USD": "US Dollar",
    "GBP": "Pound Sterling",
    "EUR": "Euro",
    "JPY": "Japanese Yen",
    "AED": "UAE Dirham",
    "IDR": "Indonesian Rupiah",
}
CHK_MAP = {  # form checkbox names per currency
    "USD": "chkUSD",
    "GBP": "chkGBP",
    "EUR": "chkEURO",  # RBI uses EURO not EUR
    "JPY": "chkYEN",
    "AED": "chkAED",
    "IDR": "chkIDR",
}
URL = "https://www.rbi.org.in/scripts/referenceratearchive.aspx"


def log(msg: str):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ----------------------------- HTTP helpers --------------------------------

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return r.status, r.read(), dict(r.headers)


def http_post(url, data: dict, headers: dict, cookies: str):
    body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    if cookies:
        h["Cookie"] = cookies
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return r.status, r.read(), dict(r.headers)


def parse_cookies(headers: dict) -> str:
    """Pull Set-Cookie values and join them."""
    out = []
    for k, v in headers.items():
        if k.lower() == "set-cookie":
            # Each Set-Cookie may appear once; sometimes multiple comma-separated
            for piece in v.split(","):
                name_val = piece.split(";", 1)[0].strip()
                if name_val:
                    out.append(name_val)
    return "; ".join(out)


def extract_field(html: str, name: str) -> str:
    """Pull an <input name="X" value="..."> value from raw HTML."""
    m = re.search(
        rf'<input[^>]*name="{re.escape(name)}"[^>]*value="([^"]*)"',
        html, flags=re.IGNORECASE,
    )
    if not m:
        # Try value before name
        m = re.search(
            rf'<input[^>]*value="([^"]*)"[^>]*name="{re.escape(name)}"',
            html, flags=re.IGNORECASE,
        )
    return m.group(1) if m else ""


# ----------------------------- HTML parsing --------------------------------

def parse_table(html: str) -> dict[str, list[dict]]:
    """Pull currency rows out of the RBI reference rate table.

    RBI's table headers look like:
        Date | USD (INR / 1 USD) | GBP (INR / 1 GBP) | ... | JPY (INR / 100 JPY) | ... | IDR (INR / 10000 IDR)
    Dates are DD/MM/YYYY.
    """
    out: dict[str, list[dict]] = {c: [] for c in CURRENCIES}

    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.IGNORECASE | re.DOTALL)
    if not tables:
        return out

    # Pick the data table. Distinguishing features:
    #   1. Has multiple <tr> with <td> rows (not just a search form with <th>)
    #   2. Header row contains "INR /" denominator notation (e.g. "USD (INR / 1 USD)")
    #   3. Data rows contain a date-like first cell
    target = None
    for t in tables:
        if "INR /" not in t.upper():
            continue
        rows_t = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.DOTALL)
        if len(rows_t) < 2:
            continue
        # First cell of second row must look like a date (DD/MM/YYYY)
        first_data_cells = re.findall(r"<td[^>]*>(.*?)</td>", rows_t[1], re.DOTALL)
        if not first_data_cells:
            continue
        first_text = re.sub(r"<[^>]+>", " ", first_data_cells[0]).strip()
        if parse_date(first_text) is None:
            continue
        target = t
        break
    if target is None:
        # Last resort: the table with the most data rows
        def score(t):
            return len(re.findall(r"<td", t))
        target = max(tables, key=score)

    def clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"&nbsp;", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", target, re.IGNORECASE | re.DOTALL)
    if not rows:
        return out

    # Detect currency columns from header row — match by substring
    header_cells = [clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.DOTALL)]
    col_map: list[tuple[int, str, int]] = []  # (col_idx, currency, per_n)
    for i, h in enumerate(header_cells):
        if not h:
            continue
        upper = h.upper()
        for curr in CURRENCIES:
            if curr in upper:
                # Try to extract "INR / N CURR" denominator
                m = re.search(r"INR\s*/\s*(\d+)\s*" + curr, upper)
                per_n = int(m.group(1)) if m else 1
                col_map.append((i, curr, per_n))
                break

    # Parse data rows
    for row in rows[1:]:
        cells = [clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)]
        if not cells:
            continue
        date_text = cells[0]
        d = parse_date(date_text)
        if d is None:
            continue
        iso = d.isoformat()
        for col_idx, curr, per_n in col_map:
            if col_idx >= len(cells):
                continue
            raw = cells[col_idx].replace(",", "").strip()
            try:
                rate = float(raw)
            except (TypeError, ValueError):
                continue
            out[curr].append({
                "date": iso,
                "rate": rate,                      # RBI-stated rate (per N units)
                "per_n": per_n,                    # denominator (1, 100, 10000)
                "per1": rate / per_n if per_n else rate,  # normalized to per 1 unit
            })
    return out


def parse_date(s: str):
    """Try a handful of RBI date formats. Returns date or None."""
    s = s.strip()
    if not s:
        return None
    formats = [
        "%d/%m/%Y", "%d-%m-%Y",        # RBI archive: 03/07/2026
        "%d %b %Y", "%d %B %Y",        # 03 Jul 2026
        "%d-%b-%Y", "%d-%B-%Y",
        "%d %b, %Y", "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ----------------------------- Fetch loop ----------------------------------

def fetch_range(start: date, end: date, max_retries: int = 3) -> dict[str, list[dict]]:
    """POST to the archive page for the given date range. Returns parsed rows."""
    headers_get = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for attempt in range(max_retries):
        try:
            # 1. GET to obtain VIEWSTATE + cookies
            status, body, hdrs = http_get(URL, headers=headers_get)
            if status != 200:
                raise RuntimeError(f"GET status {status}")
            html = body.decode("utf-8", errors="replace")
            cookies = parse_cookies(hdrs)

            viewstate = extract_field(html, "__VIEWSTATE")
            viewstategen = extract_field(html, "__VIEWSTATEGENERATOR")
            eventval = extract_field(html, "__EVENTVALIDATION")
            if not viewstate:
                raise RuntimeError("__VIEWSTATE not found")

            # 2. POST with the form
            data = {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": viewstategen,
                "__EVENTVALIDATION": eventval,
                "UsrFontCntr$txtSearch": "",
                "UsrFontCntr$btn": "",
                "chkAll": "on",  # select all currencies
                "txtFromDate": start.strftime("%d/%m/%Y"),
                "txtToDate": end.strftime("%d/%m/%Y"),
                "btnSubmit": "Submit",
            }
            status, body, _ = http_post(URL, data, headers_get, cookies)
            if status != 200:
                # 504/503 are common — back off
                if status in (502, 503, 504):
                    raise RuntimeError(f"POST status {status} (server overloaded — will retry)")
                raise RuntimeError(f"POST status {status}")
            html = body.decode("utf-8", errors="replace")
            # Debug: save response
            if os.environ.get("REF_DEBUG"):
                debug_path = BASE_DIR / "data" / f"_debug_{start}_{end}.html"
                debug_path.write_text(html, encoding="utf-8")
                log(f"  [debug] wrote {debug_path}")
            rows = parse_table(html)
            total = sum(len(v) for v in rows.values())
            if total == 0:
                # Possibly weekend/holiday — return empty rather than retry
                log(f"  Fetched {start} → {end}: 0 currency-days (likely no rates for this range)")
                return rows
            log(f"  Fetched {start} → {end}: {total} currency-days")
            return rows
        except Exception as e:
            wait = 10 * (attempt + 1)
            log(f"  Attempt {attempt+1}/{max_retries} failed: {e}; waiting {wait}s")
            time.sleep(wait)
    log(f"  All attempts failed for {start} → {end}")
    return {c: [] for c in CURRENCIES}


# ----------------------------- Storage -------------------------------------

def load_existing() -> dict:
    if not OUT.exists():
        return {"currencies": CURRENCIES, "rates": {c: [] for c in CURRENCIES}}
    try:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        if "rates" not in d:
            d["rates"] = {c: [] for c in CURRENCIES}
        for c in CURRENCIES:
            d["rates"].setdefault(c, [])
        return d
    except Exception:
        return {"currencies": CURRENCIES, "rates": {c: [] for c in CURRENCIES}}


def merge(existing: dict, fresh: dict[str, list[dict]]) -> dict:
    """Merge new rows into existing, dedupe by date, sort ascending."""
    out = existing
    for curr in CURRENCIES:
        by_date: dict[str, dict] = {}
        for r in out["rates"].get(curr, []):
            by_date[r["date"]] = r
        for r in fresh.get(curr, []):
            # Always overwrite with freshest (in case RBI corrected a print)
            by_date[r["date"]] = r
        merged = [by_date[d] for d in sorted(by_date)]
        out["rates"][curr] = merged
    return out


# ----------------------------- Main -----------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30, help="How many days back to fetch (default 30)")
    p.add_argument("--today", action="store_true", help="Fetch only today (single-day range)")
    p.add_argument("--start", type=str, help="Override start date (YYYY-MM-DD)")
    p.add_argument("--end", type=str, help="Override end date (YYYY-MM-DD)")
    p.add_argument("--chunk-days", type=int, default=14,
                   help="How many days per HTTP request (smaller = less 504 risk). Default 14.")
    args = p.parse_args()

    today = date.today()
    if args.today:
        start = end = today
    elif args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        end = today
        start = today - timedelta(days=args.days)

    log(f"Fetching RBI Reference Rates: {start} → {end}")

    existing = load_existing()
    last_per_curr = {}
    for c in CURRENCIES:
        rs = existing["rates"].get(c, [])
        if rs:
            last_per_curr[c] = max(r["date"] for r in rs)
    earliest_existing = min(last_per_curr.values(), default="9999-99-99")
    if last_per_curr and start < datetime.strptime(earliest_existing, "%Y-%m-%d").date():
        log(f"  Capping start to earliest existing date {earliest_existing}")
        start = datetime.strptime(earliest_existing, "%Y-%m-%d").date()

    # Chunk the range — RBI's archive often returns 504 on large windows
    all_fresh: dict[str, list[dict]] = {c: [] for c in CURRENCIES}
    chunk_days = args.chunk_days
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        log(f"  Chunk {cur} → {chunk_end}")
        rows = fetch_range(cur, chunk_end)
        for c in CURRENCIES:
            all_fresh[c].extend(rows.get(c, []))
        # Pause between chunks to be polite
        time.sleep(3)
        cur = chunk_end + timedelta(days=1)

    merged = merge(existing, all_fresh)
    merged["generatedAt"] = datetime.utcnow().isoformat() + "Z"
    merged["source"] = "RBI Reference Rate Archive (referenceratearchive.aspx)"
    merged["currencies"] = CURRENCIES
    merged["meta"] = {
        c: {"name": NAMES[c], "per_n": UNITS_PER[c],
             "unit_label": f"INR / {UNITS_PER[c]} {c}" if UNITS_PER[c] > 1 else f"INR / 1 {c}"}
        for c in CURRENCIES
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    log(f"Wrote {OUT}")

    for c in CURRENCIES:
        n = len(merged["rates"].get(c, []))
        if n:
            last = merged["rates"][c][-1]
            log(f"  {c}: {n} rows, latest = {last['rate']} on {last['date']}")
        else:
            log(f"  {c}: no data")
    return 0


if __name__ == "__main__":
    sys.exit(main())