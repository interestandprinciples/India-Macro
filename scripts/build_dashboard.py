#!/usr/bin/env python3
"""
Build a self-contained dashboard HTML with the JSON dataset embedded inline,
so the page works without any web server (file://, double-click, etc.).

Also produces the bare JSON alongside, in case anything else wants to read it.

Usage:
  python3 scripts/build_dashboard.py                  # default: data + dashboard
  python3 scripts/build_dashboard.py --no-embed       # only the JSON file
  python3 scripts/build_dashboard.py --watch          # rebuild when Excel changes
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
HTML_TEMPLATE = SCRIPT_DIR.parent / "dashboard" / "index.html"
HTML_OUT = SCRIPT_DIR.parent / "dashboard" / "index.html"   # in-place rebuild
JSON_OUT = SCRIPT_DIR.parent / "data" / "macro_data.json"
LIVE_OUT = SCRIPT_DIR.parent / "data" / "live_rates.json"

EMBED_MARKER = "/* === EMBED:DATA === */"
EMBED_END    = "/* === /EMBED:DATA === */"
# Anchor for the live-data block. We keep it as a JS comment line so we can find
# and re-embed on every build (the previous version was a /* ... */ comment
# that disappeared after first replacement, breaking subsequent rebuilds).
LIVE_ANCHOR_START = "/* === EMBED:LIVE === */"
LIVE_ANCHOR_END   = "/* === /EMBED:LIVE === */"
REF_ANCHOR_START  = "/* === EMBED:REF_RATES === */"
REF_ANCHOR_END    = "/* === /EMBED:REF_RATES === */"


def run_extract():
    import subprocess
    res = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "extract_data.py")],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise SystemExit("extract_data.py failed")
    return res.stdout


def build_js_wrappers():
    """Convert the JSON files into JS wrappers that can be loaded from file://
    via <script src="...">. This makes the curate page self-contained.
    """
    DATA_DIR = BASE_DIR / "data"
    for json_name, js_name, var_name in [
        ("macro_data.json", "macro_data.js", "MACRO_DATA"),
        ("curation.json",  "curation.js",   "CURATION"),
        ("live_rates.json","live_rates.js", "LIVE_DATA"),
        ("reference_rates.json", "reference_rates.js", "REF_RATES"),
        ("crude_oil.json", "crude_oil.js", "CRUDE_OIL"),
        ("mospi_wb.json",  "mospi_wb.js",   "MOSPI_WB"),
    ]:
        src = DATA_DIR / json_name
        dst = DATA_DIR / js_name
        if not src.exists():
            if dst.exists():
                # Keep the stale wrapper if we don't have fresh data
                continue
            # Write a safe null stub
            dst.write_text(f"window.{var_name} = null;\n", encoding="utf-8")
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        dst.write_text(f"window.{var_name} = {json.dumps(data, ensure_ascii=False)};\n", encoding="utf-8")


def embed_data(embed: bool):
    if not HTML_TEMPLATE.exists():
        raise SystemExit(f"Missing template: {HTML_TEMPLATE}")
    html = HTML_TEMPLATE.read_text(encoding="utf-8")

    if embed:
        json_text = JSON_OUT.read_text(encoding="utf-8")
        embed_block = f"{EMBED_MARKER}\nwindow.MACRO_DATA = {json_text};\n{EMBED_END}"

        if EMBED_MARKER in html:
            # replace existing block (keep everything before and after)
            before, _, rest = html.partition(EMBED_MARKER)
            _, _, after = rest.partition(EMBED_END)
            new = before + embed_block + after
        else:
            # insert just before </script> of the inline script block
            anchor = "/* go */\nload();"
            if anchor not in html:
                raise SystemExit("Could not locate the bootstrap line in the HTML template")
            new = html.replace(anchor, embed_block + "\n\n" + anchor, 1)

        # Embed the live snapshot too, if available
        # Always replace the live block on each build (previous version used a
        # single placeholder that disappeared after first use).
        if LIVE_OUT.exists():
            live_text = LIVE_OUT.read_text(encoding="utf-8").strip()
            live_block = f"{LIVE_ANCHOR_START}\nwindow.LIVE_DATA = {live_text};\n{LIVE_ANCHOR_END}"
        else:
            live_block = f"{LIVE_ANCHOR_START}\nwindow.LIVE_DATA = null;  // no snapshot yet\n{LIVE_ANCHOR_END}"

        if LIVE_ANCHOR_START in new and LIVE_ANCHOR_END in new:
            before, _, rest = new.partition(LIVE_ANCHOR_START)
            _, _, after = rest.partition(LIVE_ANCHOR_END)
            new = before + live_block + after
        else:
            # First time — insert just before the macro-data embed
            anchor = EMBED_MARKER
            if anchor in new:
                new = new.replace(anchor, live_block + "\n\n" + anchor, 1)
            else:
                # Fall back to inserting before the bootstrap call
                bootstrap = "/* go */\nload();"
                if bootstrap in new:
                    new = new.replace(bootstrap, live_block + "\n\n" + bootstrap, 1)

        # Embed the curation rules
        curation_out = BASE_DIR / "data" / "curation.json"
        curation_block_start = "/* === EMBED:CURATION === */"
        curation_block_end = "/* === /EMBED:CURATION === */"
        if curation_out.exists():
            curation_text = curation_out.read_text(encoding="utf-8").strip()
            curation_block = f'{curation_block_start}\nwindow.CURATION = {curation_text};\n{curation_block_end}'
        else:
            curation_block = f'{curation_block_start}\nwindow.CURATION = {{ default: {{ show: true, mode: "both" }}, series: {{}}, themeDefaults: {{}} }};\n{curation_block_end}'

        if curation_block_start in new and curation_block_end in new:
            before, _, rest = new.partition(curation_block_start)
            _, _, after = rest.partition(curation_block_end)
            new = before + curation_block + after
        else:
            # First time — insert just before the live data block
            if LIVE_ANCHOR_START in new:
                new = new.replace(LIVE_ANCHOR_START, curation_block + "\n\n" + LIVE_ANCHOR_START, 1)
            elif EMBED_MARKER in new:
                new = new.replace(EMBED_MARKER, curation_block + "\n\n" + EMBED_MARKER, 1)
            else:
                bootstrap = "/* go */\nload();"
                if bootstrap in new:
                    new = new.replace(bootstrap, curation_block + "\n\n" + bootstrap, 1)

        # Embed the live tickers list
        tickers_out = BASE_DIR / "data" / "live_tickers.json"
        tickers_start = "/* === EMBED:LIVE_TICKERS === */"
        tickers_end = "/* === /EMBED:LIVE_TICKERS === */"
        if tickers_out.exists():
            tickers_text = tickers_out.read_text(encoding="utf-8").strip()
            tickers_block = f'{tickers_start}\nwindow.LIVE_TICKERS = {tickers_text};\n{tickers_end}'
        else:
            tickers_block = f'{tickers_start}\nwindow.LIVE_TICKERS = null;\n{tickers_end}'

        if tickers_start in new and tickers_end in new:
            before, _, rest = new.partition(tickers_start)
            _, _, after = rest.partition(tickers_end)
            new = before + tickers_block + after
        else:
            # First time — insert just before the curation block
            if curation_block_start in new:
                new = new.replace(curation_block_start, tickers_block + "\n\n" + curation_block_start, 1)
            elif LIVE_ANCHOR_START in new:
                new = new.replace(LIVE_ANCHOR_START, tickers_block + "\n\n" + LIVE_ANCHOR_START, 1)
            else:
                bootstrap = "/* go */\nload();"
                if bootstrap in new:
                    new = new.replace(bootstrap, tickers_block + "\n\n" + bootstrap, 1)

        # Embed the RBI Reference Rates (USD/GBP/EUR/JPY/AED/IDR)
        ref_out = BASE_DIR / "data" / "reference_rates.json"
        if ref_out.exists():
            ref_text = ref_out.read_text(encoding="utf-8").strip()
            ref_block = f'{REF_ANCHOR_START}\nwindow.REF_RATES = {ref_text};\n{REF_ANCHOR_END}'
        else:
            ref_block = f'{REF_ANCHOR_START}\nwindow.REF_RATES = null;\n{REF_ANCHOR_END}'

        if REF_ANCHOR_START in new and REF_ANCHOR_END in new:
            before, _, rest = new.partition(REF_ANCHOR_START)
            _, _, after = rest.partition(REF_ANCHOR_END)
            new = before + ref_block + after
        else:
            # First time — insert just before the live tickers block
            if tickers_start in new:
                new = new.replace(tickers_start, ref_block + "\n\n" + tickers_start, 1)
            elif curation_block_start in new:
                new = new.replace(curation_block_start, ref_block + "\n\n" + curation_block_start, 1)
            else:
                bootstrap = "/* go */\nload();"
                if bootstrap in new:
                    new = new.replace(bootstrap, ref_block + "\n\n" + bootstrap, 1)

        # Embed MoSPI / World Bank long-term macro
        mospi_out = BASE_DIR / "data" / "mospi_wb.json"
        mospi_start = "/* === EMBED:MOSPI === */"
        mospi_end   = "/* === /EMBED:MOSPI === */"
        if mospi_out.exists():
            mospi_text = mospi_out.read_text(encoding="utf-8").strip()
            mospi_block = f'{mospi_start}\nwindow.MOSPI_WB = {mospi_text};\n{mospi_end}'
        else:
            mospi_block = f'{mospi_start}\nwindow.MOSPI_WB = null;\n{mospi_end}'

        if mospi_start in new and mospi_end in new:
            before, _, rest = new.partition(mospi_start)
            _, _, after = rest.partition(mospi_end)
            new = before + mospi_block + after
        else:
            # First time — insert before the crude block (defined below)
            bootstrap = "/* go */\nload();"
            if bootstrap in new:
                new = new.replace(bootstrap, mospi_block + "\n\n" + bootstrap, 1)
            else:
                new = mospi_block + "\n\n" + new

        # Embed Crude Oil Indian Basket (PPAC + Brent)
        crude_out = BASE_DIR / "data" / "crude_oil.json"
        crude_start = "/* === EMBED:CRUDE === */"
        crude_end   = "/* === /EMBED:CRUDE === */"
        if crude_out.exists():
            crude_text = crude_out.read_text(encoding="utf-8").strip()
            crude_block = f'{crude_start}\nwindow.CRUDE_OIL = {crude_text};\n{crude_end}'
        else:
            crude_block = f'{crude_start}\nwindow.CRUDE_OIL = null;\n{crude_end}'

        if crude_start in new and crude_end in new:
            before, _, rest = new.partition(crude_start)
            _, _, after = rest.partition(crude_end)
            new = before + crude_block + after
        else:
            # First time — insert just before the ref rates block
            if REF_ANCHOR_START in new:
                new = new.replace(REF_ANCHOR_START, crude_block + "\n\n" + REF_ANCHOR_START, 1)
            elif tickers_start in new:
                new = new.replace(tickers_start, crude_block + "\n\n" + tickers_start, 1)
            else:
                bootstrap = "/* go */\nload();"
                if bootstrap in new:
                    new = new.replace(bootstrap, crude_block + "\n\n" + bootstrap, 1)

        HTML_OUT.write_text(new, encoding="utf-8")
        print(f"Wrote {HTML_OUT}  (with embedded JSON, {len(html.encode('utf-8')):,} → {len(new.encode('utf-8')):,} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-embed", action="store_true",
                    help="Skip embedding JSON in the HTML (JSON only)")
    ap.add_argument("--no-extract", action="store_true",
                    help="Skip re-extracting from Excel (use existing JSON)")
    ap.add_argument("--watch", action="store_true",
                    help="Rebuild when the source Excel files change")
    args = ap.parse_args()

    if not args.no_extract:
        run_extract()
    build_js_wrappers()
    if not args.no_embed:
        embed_data(embed=True)

    if not args.watch:
        return

    # Watch mode
    import hashlib
    sources = [
        BASE_DIR / "50 Macroeconomic Indicators.xlsx",
        BASE_DIR / "Other Macroeconomic Indicators.xlsx",
        SCRIPT_DIR / "extract_data.py",
        HTML_TEMPLATE,
    ]
    last = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.exists()}
    print(f"[{datetime.now():%H:%M:%S}] Watching for changes… Ctrl-C to stop")
    try:
        while True:
            time.sleep(2)
            changed = False
            for p, prev in last.items():
                if not p.exists():
                    continue
                cur = hashlib.sha256(p.read_bytes()).hexdigest()
                if cur != prev:
                    print(f"[{datetime.now():%H:%M:%S}] {p.name} changed")
                    last[p] = cur
                    changed = True
            if changed:
                try:
                    run_extract()
                    if not args.no_embed:
                        embed_data(embed=True)
                except SystemExit as e:
                    print(f"  rebuild failed: {e}")
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()