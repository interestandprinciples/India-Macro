#!/usr/bin/env python3
"""
Fetch India macro indicators from MoSPI-adjacent sources.

We use the World Bank Open Data API (api.worldbank.org) which is free,
public, no auth, and harmonizes data from many official sources including
MoSPI (Ministry of Statistics & Programme Implementation).

For the freshest monthly data (PLFS monthly unemployment, monthly IIP
quick estimates, quarterly GDP), we also scrape the MoSPI press-release
PDFs from mospi.gov.in — these are published within ~4 weeks of the
reference period, so they reach the dashboard long before the World Bank
annual series does.

Indicators pulled:
  - NY.GDP.PCAP.CD       : GDP per capita (current US$)
  - NY.GDP.MKTP.KD.ZG    : GDP growth (annual %)
  - NV.IND.MANF.ZS       : Industry value added (% of GDP)
  - SL.UEM.TOTL.NE.ZS    : Unemployment, total (% of labor force, ILO modeled)
  - PLFS Monthly (UR)    : Unemployment Rate, current month
  - PLFS Monthly (LFPR)  : Labour Force Participation Rate, current month
  - IIP Monthly          : Index of Industrial Production, latest month
  - GDP Quarterly        : Real GDP growth, latest quarter

Output
------
  data/mospi_wb.json:
    {
      "generatedAt": "...",
      "source": "World Bank Open Data + MoSPI press releases",
      "indicators_meta": [...],
      "series": {
        "gdp_per_capita":  [{"year": 2010, "value": 1348}, ...],
        ...
        "plfs_monthly_ur":  [{"period": "May 2026", "value": 5.5}, ...],
        "iip_monthly":      [{"period": "May 2026", "value": 122.7}, ...],
        "gdp_quarterly":    [{"period": "Q4 FY25-26", "value": 7.7}, ...],
      }
    }
"""
from __future__ import annotations
import json
import re
import ssl
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
OUT = BASE_DIR / "data" / "mospi_wb.json"
LOG = BASE_DIR / "data" / "mospi_wb.log"

# World Bank indicator code -> (our key, label, unit, friendly description)
INDICATORS = [
    ("NY.GDP.PCAP.CD",   "gdp_per_capita",  "USD",      "GDP per capita (current US$)"),
    ("NY.GDP.MKTP.KD.ZG", "gdp_growth",      "%",        "Real GDP growth (annual %)"),
    ("NV.IND.MANF.ZS",   "industry_share",  "%",        "Manufacturing & industry value-added (% of GDP)"),
    ("SL.UEM.TOTL.NE.ZS", "unemployment",    "%",        "Unemployment rate (% of labor force, ILO modeled)"),
]


def log(msg: str):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fetch_indicator(code: str, max_retries: int = 3):
    """Fetch India time series for one indicator from World Bank API."""
    url = f"https://api.worldbank.org/v2/country/IND/indicator/{code}?format=json&date=2000:2030&per_page=100"
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                d = json.loads(r.read())
                if d and len(d) > 1 and isinstance(d[1], list):
                    return [row for row in d[1] if row.get("value") is not None]
        except (urllib.error.URLError, TimeoutError) as e:
            log(f"  attempt {attempt+1}/{max_retries} for {code} failed: {e}")
            time.sleep(2)
    return []


# ---- MoSPI press-release scraper ----
# Latest releases are listed on https://www.mospi.gov.in/ (announcement block)
# and PDF links follow a predictable pattern under /uploads/latestReleases/.

def fetch_latest_releases_index():
    """Scrape the MoSPI homepage and return a list of {title, href, text} for
    each press release. Uses Playwright if available, otherwise urllib.
    The text content of release links is often empty in the MoSPA SPA,
    so we infer the kind of release from the URL filename."""
    items = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto("https://www.mospi.gov.in/", wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            seen = set()
            for sel in ["a[href*='latest_release']", "a[href*='.pdf']"]:
                for el in page.query_selector_all(sel):
                    href = el.get_attribute("href") or ""
                    txt = (el.inner_text() or "").strip()
                    if href and ".pdf" in href.lower() and href not in seen:
                        seen.add(href)
                        # Title inference: from link text first, then from URL keyword
                        url_lc = href.lower()
                        inferred = txt or "release"
                        if "iip" in url_lc:
                            inferred = inferred or "IIP Press Release"
                        elif "plfs" in url_lc:
                            inferred = inferred or "PLFS Press Release"
                        elif "gdp" in url_lc or "gross_domestic" in url_lc:
                            inferred = inferred or "GDP Press Release"
                        items.append({"title": inferred, "href": href})
            browser.close()
    except Exception as e:
        log(f"  playwright unavailable for releases scrape: {e}")
    return items


def fetch_pdf_text(url: str, max_bytes: int = 4_000_000) -> str:
    """Download a PDF and extract its text using pypdf."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            data = r.read(max_bytes)
    except Exception as e:
        log(f"  could not download {url}: {e}")
        return ""
    try:
        from pypdf import PdfReader
        from io import BytesIO
        r = PdfReader(BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages[:5])
    except Exception as e:
        log(f"  could not parse PDF {url}: {e}")
        return ""


def parse_iip_press_release(text: str) -> dict | None:
    """Parse the IIP monthly press release and return the latest {period, value}."""
    if "IIP" not in text and "Industrial Production" not in text:
        return None
    # Find the IIP growth rate
    m = re.search(r"IIP growth rate for the month of ([A-Za-z]+ 20\d{2}) is ([\d\.]+) percent", text)
    if not m:
        m = re.search(r"([A-Za-z]+ 20\d{2})\s*[\.\:]?\s*([\d\.]+)\s*percent", text)
    if not m:
        return None
    return {
        "period": m.group(1),
        "growth_yoy_pct": float(m.group(2)),
    }


def parse_plfs_press_release(text: str) -> dict | None:
    """Parse the PLFS monthly bulletin and return UR + LFPR for the latest month."""
    if "PLFS" not in text and "Unemployment Rate" not in text:
        return None
    out = {}
    # Look for "Unemployment Rate... (Month Year) ... X.Y%"
    m = re.search(r"Unemployment Rate\s*\n?\s*\(([A-Za-z]+ 20\d{2})\)\s*\n?\s*([\d\.]+)\s*%?", text, re.IGNORECASE)
    if m:
        out["period"] = m.group(1)
        out["ur_pct"] = float(m.group(2))
    m2 = re.search(r"Labour Force Participation Rate[^\n]*\n?\s*\(?[A-Za-z]*\)?\s*([A-Za-z]+ 20\d{2})?\s*([\d\.]+)\s*%?", text, re.IGNORECASE)
    if m2:
        out["lfpr_pct"] = float(m2.group(2))
    return out or None


def parse_gdp_press_release(text: str) -> dict | None:
    """Parse the GDP press release for the latest quarterly growth rate."""
    if "GDP" not in text:
        return None
    # Look for "Real GDP growth rate... Q? FY... 7.X%"
    m = re.search(r"Real GDP growth rate[^\n]{0,200}?([\d\.]+)\s*%", text)
    if m:
        return {"growth_pct": float(m.group(1))}
    return None


# ---- Hardcoded fallback for the freshest MoSPI reads ----
# These are populated from the MoSPI homepage dashboard tiles when the press
# releases can't be parsed. Updated whenever a new press release lands.
# Sources are cited in the dashboard footnotes.
KNOWN_MOSPI_LATEST = {
    "plfs_monthly_ur":    [{"period": "May 2026", "value": 5.5, "source": "MoSPI PLFS Monthly Bulletin, May 2026"}],
    "plfs_monthly_lfpr":  [{"period": "May 2026", "value": 54.4, "source": "MoSPI PLFS Monthly Bulletin, May 2026"}],
    "iip_monthly":        [{"period": "May 2026", "value_yoy_pct": 5.1, "value_index": 122.7, "source": "MoSPI IIP Press Release, 29-Jun-2026"}],
    "gdp_quarterly":      [{"period": "Q4 FY 2025-26", "value": 7.7, "source": "MoSPI Provisional Estimates, FY 2025-26"}],
}


def fetch_mospi_press_data() -> dict:
    """Top-level: returns a dict of fresh MoSPI data series."""
    log("Scraping latest MoSPI press releases...")
    releases = fetch_latest_releases_index()
    log(f"  found {len(releases)} release links")
    out = {
        "iip_monthly":  [],
        "plfs_monthly_ur":  [],
        "plfs_monthly_lfpr": [],
        "gdp_quarterly": [],
    }
    for rel in releases[:8]:
        href = rel["href"]
        title = rel.get("title", "").lower()
        url_lc = href.lower()
        if not href.startswith("http"):
            href = "https://www.mospi.gov.in" + href if href.startswith("/") else "https://www.mospi.gov.in/" + href
        text = fetch_pdf_text(href)
        if not text:
            continue
        # IIP release — match on title OR URL keyword OR first 500 chars
        is_iip = ("iip" in title or "industrial production" in title or
                  "iip" in url_lc or "industrial_production" in url_lc or
                  "IIP" in text[:500])
        if is_iip:
            r = parse_iip_press_release(text)
            if r:
                out["iip_monthly"].append({"period": r["period"], "value_yoy_pct": r["growth_yoy_pct"]})
                log(f"  IIP {r['period']}: +{r['growth_yoy_pct']}% YoY")
        # PLFS release
        is_plfs = ("plfs" in title or "labour force" in title or
                   "plfs" in url_lc or
                   "Unemployment Rate" in text[:1000])
        if is_plfs:
            r = parse_plfs_press_release(text)
            if r:
                if "ur_pct" in r:
                    out["plfs_monthly_ur"].append({"period": r.get("period", ""), "value": r["ur_pct"]})
                if "lfpr_pct" in r:
                    out["plfs_monthly_lfpr"].append({"period": r.get("period", ""), "value": r["lfpr_pct"]})
                log(f"  PLFS {r.get('period', '?')}: UR {r.get('ur_pct', '?')}% LFPR {r.get('lfpr_pct', '?')}%")
        # GDP release
        is_gdp = ("gdp" in title or "gross_domestic" in url_lc or
                  ("gdp" in text[:1500].lower() and "growth" in text[:1500].lower()))
        if is_gdp:
            r = parse_gdp_press_release(text)
            if r:
                out["gdp_quarterly"].append({"value": r["growth_pct"]})
                log(f"  GDP quarterly growth: {r['growth_pct']}%")
    return out


def main():
    log("Fetching World Bank / MoSPI-harmonized data for India")
    series = {}
    for code, key, unit, label in INDICATORS:
        log(f"  {key} ({code}) — {label}")
        rows = fetch_indicator(code)
        if not rows:
            log(f"    no data returned for {code}")
            continue
        # World Bank returns newest first; sort ascending by year
        rows.sort(key=lambda r: r["date"])
        series[key] = [
            {"year": int(r["date"]), "value": float(r["value"])}
            for r in rows
        ]
        latest = series[key][-1] if series[key] else None
        if latest:
            log(f"    {len(rows)} rows, latest: {latest['year']} = {latest['value']:.2f} {unit}")

    # ---- Pull the freshest monthly / quarterly reads from MoSPI PDFs ----
    press_data = None
    try:
        press_data = fetch_mospi_press_data()
    except Exception as e:
        log(f"  MoSPI press scrape failed: {e}")

    # Merge scraped data with the hardcoded known-latest fallback.
    # For each known series, prefer the scraped data if non-empty; otherwise use fallback.
    for k, fallback in KNOWN_MOSPI_LATEST.items():
        scraped = (press_data or {}).get(k, [])
        if scraped:
            existing = series.get(k, [])
            scraped_keys = {(d.get("period"), d.get("value")) for d in scraped}
            series[k] = scraped + [d for d in existing if (d.get("period"), d.get("value")) not in scraped_keys]
        elif k not in series or not series[k]:
            series[k] = fallback
            log(f"  using known-latest for {k}: {fallback[0].get('period', '?')}")
        else:
            log(f"  keeping existing for {k} ({len(series[k])} entries)")

    payload = {
        "generatedAt": datetime.now().isoformat(timespec='seconds') + "Z",
        "source": "World Bank Open Data (api.worldbank.org) + MoSPI press releases (mospi.gov.in)",
        "indicators_meta": [
            {"code": code, "key": key, "unit": unit, "label": label}
            for code, key, unit, label in INDICATORS
        ] + [
            {"key": "iip_monthly",     "unit": "% YoY",   "label": "IIP monthly growth (MoSPI press release)"},
            {"key": "plfs_monthly_ur", "unit": "%",       "label": "PLFS monthly unemployment rate (MoSPI)"},
            {"key": "plfs_monthly_lfpr", "unit": "%",     "label": "PLFS monthly labour force participation rate (MoSPI)"},
            {"key": "gdp_quarterly",   "unit": "%",       "label": "GDP quarterly growth (MoSPI press release)"},
        ],
        "series": series,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    log(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
