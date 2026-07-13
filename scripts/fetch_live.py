#!/usr/bin/env python3
"""
Fetch live market rates from public sources (no API keys needed) and write
them to data/live_rates.json. Run by launchd every ~15 minutes during
market hours so the dashboard always shows recent prices.

Sources
-------
* USD/INR           — open.er-api.com (free, no key, CORS-friendly)
* NIFTY 50, NIFTY
  Bank, INDIA VIX   — NSE India API (needs User-Agent + Referer)
* US 10Y Yield,
  Gold, Brent       — Yahoo Finance v8/finance chart (query2 → query1 fallback)

Output
------
  data/live_rates.json:
    {
      "generatedAt": "2026-07-03T07:55:00Z",
      "source": "open.er-api.com + NSE + Yahoo Finance",
      "rates": {
        "usdinr":   { "price": 95.39, "prevClose": 94.66, "time": ..., "state": "live", "source": "open.er-api.com" },
        "nifty":    { "price": 24308.05, "prevClose": 24175.7, ... },
        ...
      }
    }
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

try:
    import certifi
    SSL_CTX = __import__("ssl").create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = __import__("ssl").create_default_context()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
OUT = BASE_DIR / "data" / "live_rates.json"
LOG = BASE_DIR / "data" / "live.log"


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.status, r.read()


# --------- Sources --------------------------------------------------

def fetch_usdinr_yfinance():
    """yfinance USDINR=X — true live forex (offshore USD/INR futures, ~24/7).

    open.er-api.com only refreshes a few times a day, so we use yfinance first
    and fall back to it if it fails. yfinance is also used for US 10Y / Gold /
    Brent, so the dependency is already in place.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed (run: pip3 install yfinance)")
    t = yf.Ticker("USDINR=X")
    fast = {}
    try:
        fast = t.fast_info or {}
    except Exception:
        pass
    # fast_info gives last price + last trade time (truly live during forex hours)
    last_price = fast.get("lastPrice") or fast.get("last_price")
    last_ms = fast.get("last_trade_time_ms") or fast.get("lastTradeTime")
    if last_price is None:
        # Fallback: 5d history
        h = t.history(period="5d", auto_adjust=False)
        if h is None or len(h) == 0:
            raise RuntimeError("yfinance USDINR=X: no data")
        closes = h["Close"].dropna()
        if closes.empty:
            raise RuntimeError("yfinance USDINR=X: empty closes")
        last_price = float(closes.iloc[-1])
        last_ts = h.index[-1]
        last_ms = int(last_ts.timestamp() * 1000) if hasattr(last_ts, "timestamp") else None
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
    else:
        # Try to get prevClose from history
        prev = None
        try:
            h = t.history(period="5d", auto_adjust=False)
            if h is not None and len(h) >= 2:
                closes = h["Close"].dropna()
                prev = float(closes.iloc[-2])
        except Exception:
            pass
    return {
        "price": float(last_price),
        "prevClose": prev,
        "time": last_ms,
        "state": "live",
        "name": "USD/INR (offshore)",
        "source": "Yahoo Finance USDINR=X (live forex)",
    }


def fetch_usdinr_openfx():
    """open.er-api.com — only refreshes a few times/day, used as fallback.
    Returns hourly stale data; flagged with state='delayed'.
    """
    headers = {"Accept": "application/json"}
    status, body = http_get("https://open.er-api.com/v6/latest/USD", headers=headers)
    if status != 200:
        raise RuntimeError(f"open.er-api HTTP {status}")
    d = json.loads(body)
    price = d.get("rates", {}).get("INR")
    if price is None:
        raise RuntimeError("INR missing in response")
    time_unix = d.get("time_last_update_unix", 0)
    age_hours = (time.time() - time_unix) / 3600
    return {
        "price": float(price),
        "prevClose": None,
        "time": time_unix * 1000,
        # 'delayed' if older than 1 hour, 'live' only if very fresh
        "state": "live" if age_hours < 1 else "delayed",
        "name": "USD/INR",
        "source": f"open.er-api.com (refreshed {age_hours:.1f}h ago)",
    }


def fetch_usdinr():
    """Try yfinance first (true live), fall back to open.er-api.com (delayed)."""
    try:
        return fetch_usdinr_yfinance()
    except Exception as e:
        log(f"  USD/INR yfinance failed ({e}); falling back to open.er-api.com")
        return fetch_usdinr_openfx()


def fetch_nse_indices():
    """NSE India — needs UA + Referer."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }
    status, body = http_get("https://www.nseindia.com/api/allIndices", headers=headers)
    if status != 200:
        raise RuntimeError(f"NSE HTTP {status}")
    d = json.loads(body)
    rows = {r["index"]: r for r in d.get("data", [])}
    out = {}

    def make(name):
        row = rows.get(name)
        if not row:
            raise RuntimeError(f"NSE index missing: {name}")
        price = row.get("last")
        prev = row.get("previousClose")
        ts_text = row.get("timestamp")  # e.g. "03-Jul-2026 15:30:00"
        return {
            "price": float(price) if price is not None else None,
            "prevClose": float(prev) if prev is not None else None,
            "time": None,
            "state": "live" if price is not None else "closed",
            "name": name,
            "source": "NSE India",
        }

    out["nifty"] = make("NIFTY 50")
    out["bank"] = make("NIFTY BANK")
    out["vix"] = make("INDIA VIX")
    return out


def fetch_yfinance(symbol):
    """Use the yfinance library — it talks to Yahoo via cookies/crumb auth,
    which is more reliable than the public chart endpoint (which is rate-limited).
    """
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed (run: pip3 install yfinance)")
    try:
        t = yf.Ticker(symbol)
        h = t.history(period="5d", auto_adjust=False)
    except Exception as e:
        raise RuntimeError(str(e))
    if h is None or len(h) < 1:
        raise RuntimeError("no history")
    # Drop rows with NaN close (e.g., empty pre-market)
    closes = h["Close"].dropna()
    if closes.empty:
        raise RuntimeError("all NaN closes")
    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
    last_ts = h.index[-1]
    last_ts_ms = int(last_ts.timestamp() * 1000) if hasattr(last_ts, 'timestamp') else None
    # Try to get a friendly name
    name = symbol
    try:
        info = t.info or {}
        name = info.get("shortName") or info.get("longName") or symbol
    except Exception:
        pass
    return {
        "price": price,
        "prevClose": prev,
        "time": last_ts_ms,
        "state": "live",
        "name": name,
        "source": "Yahoo Finance (via yfinance)",
    }


# --------- Orchestration -------------------------------------------

def fetch_all():
    result = {"generatedAt": datetime.utcnow().isoformat() + "Z"}
    rates = {}

    # USD/INR
    try:
        rates["usdinr"] = fetch_usdinr()
        log(f"  USD/INR: {rates['usdinr']['price']}")
    except Exception as e:
        log(f"  USD/INR: FAILED ({e})")
        rates["usdinr"] = {"error": str(e)}

    # NIFTY / NIFTY Bank / INDIA VIX
    try:
        nse = fetch_nse_indices()
        for k, v in nse.items():
            rates[k] = v
            log(f"  {k}: {v['price']}")
    except Exception as e:
        log(f"  NSE: FAILED ({e})")
        for k in ("nifty", "bank", "vix"):
            rates[k] = {"error": str(e)}

    # US 10Y, Gold, Brent (yfinance — more reliable than public Yahoo API)
    yahoo_specs = [("us10y", "^TNX"), ("gold", "GC=F"), ("brent", "BZ=F")]
    for k, sym in yahoo_specs:
        try:
            rates[k] = fetch_yfinance(sym)
            log(f"  {k}: {rates[k]['price']}")
        except Exception as e:
            log(f"  {k}: FAILED ({e})")
            rates[k] = {"error": str(e)}

    result["rates"] = rates
    return result


def main():
    log("Fetching live rates…")
    try:
        data = fetch_all()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(OUT)
        log(f"Wrote {OUT}")
    except Exception as e:
        log(f"FATAL: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())