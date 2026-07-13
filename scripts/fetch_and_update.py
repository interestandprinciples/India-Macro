#!/usr/bin/env python3
"""
Daily fetch: download the two RBI macro-indicator Excel files from DBIE
(data.rbi.org.in), compare against the existing copies, and refresh the
consolidated JSON if anything changed.

This script is designed to be run unattended by a macOS launchd job
(see scripts/com.rbi.macro.fetch.plist).

Usage
-----
  python3 scripts/fetch_and_update.py                  # normal daily run
  python3 scripts/fetch_and_update.py --force         # refresh even if unchanged
  python3 scripts/fetch_and_update.py --quiet         # no console output
  python3 scripts/fetch_and_update.py --dry-run       # download but don't write
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import urllib.request
import urllib.error

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
FOLDER_50 = BASE_DIR / "50 Macroeconomic Indicators.xlsx"
FOLDER_OTHER = BASE_DIR / "Other Macroeconomic Indicators.xlsx"
LOG_FILE = BASE_DIR / "data" / "fetch.log"

# --- DBIE endpoints discovered from the Angular SPA bundle ---
BASE_URL = "https://data.rbi.org.in/CIMS_Gateway_DBIE/GATEWAY/SERVICES"
TOKEN_URL = f"{BASE_URL}/security_generateSessionToken"
DOWNLOAD_URL = f"{BASE_URL}/download/dbie_FileDownloadHDFSAction"
CHANNEL_KEY = "key2"

# Filenames as known to the DBIE API
FILES = [
    {"filename": "MacroeconomicIndicators", "local": FOLDER_50,
     "label": "50 Macroeconomic Indicators"},
    {"filename": "OtherMacroeconomicTimeseriesData", "local": FOLDER_OTHER,
     "label": "Other Macroeconomic Indicators"},
]


def log(msg, *, quiet=False):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    if not quiet:
        print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_session_token():
    """POST to /security_generateSessionToken and read the response header."""
    req = urllib.request.Request(
        TOKEN_URL,
        data=b'{}',
        headers={
            "Content-Type": "application/json",
            "datatype": "application/json",
            "channelkey": CHANNEL_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        token = resp.headers.get("authorization", "").strip()
    if not token:
        raise RuntimeError("DBIE: empty session token in response")
    return token


def download_file(filename: str, token: str) -> bytes:
    """POST multipart request to download the Excel file."""
    boundary = "----rbi-fetch-boundary-12345"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="requestMessage"\r\n\r\n'
        f'{{"body":{{"Filename":"{filename}"}}}}\r\n'
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        DOWNLOAD_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "channelkey": CHANNEL_KEY,
            "authorization": token,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
        data = resp.read()
    if len(data) < 4096:
        # API returned JSON error rather than xlsx
        try:
            parsed = json.loads(data)
            err = parsed.get("header", {}).get("errorMessage", "unknown error")
            raise RuntimeError(f"DBIE download error: {err}")
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(f"DBIE: response too small ({len(data)} bytes)")
    return data


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_one(filename: str, token: str, tmpdir: Path) -> Path:
    out = tmpdir / f"{filename}.xlsx"
    data = download_file(filename, token)
    out.write_bytes(data)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="Re-extract JSON even if file unchanged")
    ap.add_argument("--quiet", action="store_true", help="Suppress stdout")
    ap.add_argument("--dry-run", action="store_true",
                    help="Download files but do not overwrite or re-extract")
    args = ap.parse_args()

    quiet = args.quiet
    log("Starting daily fetch from DBIE…", quiet=quiet)

    try:
        token = get_session_token()
        log(f"Got DBIE session token (len={len(token)})", quiet=quiet)
    except (urllib.error.URLError, RuntimeError) as e:
        log(f"ERROR fetching session: {e}", quiet=quiet)
        return 1

    summary = {"fetched": [], "unchanged": [], "errors": []}

    with tempfile.TemporaryDirectory(prefix="rbi_fetch_") as tmp:
        tmpdir = Path(tmp)
        for entry in FILES:
            label = entry["label"]
            local = entry["local"]
            try:
                fresh = fetch_one(entry["filename"], token, tmpdir)
            except Exception as e:
                log(f"ERROR downloading {label}: {e}", quiet=quiet)
                summary["errors"].append({"file": label, "error": str(e)})
                continue

            old_hash = file_hash(local) if local.exists() else None
            new_hash = bytes_hash(fresh.read_bytes())

            if old_hash == new_hash and not args.force:
                log(f"  {label}: unchanged (sha256={new_hash[:12]}…)", quiet=quiet)
                summary["unchanged"].append(label)
                continue

            if args.dry_run:
                log(f"  {label}: would update (old={old_hash[:12] if old_hash else '∅'}, new={new_hash[:12]})", quiet=quiet)
                summary["fetched"].append(label)
                continue

            # Archive the old file if it exists
            if local.exists():
                arch_dir = BASE_DIR / "data" / "archive"
                arch_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(local, arch_dir / f"{local.stem}_{stamp}.xlsx")
                # Keep only the most recent 14 archives per file
                archives = sorted(arch_dir.glob(f"{local.stem}_*.xlsx"))
                for old in archives[:-14]:
                    old.unlink()

            # Atomic replace
            local.write_bytes(fresh.read_bytes())
            log(f"  {label}: updated ({local.stat().st_size:,} bytes, sha256={new_hash[:12]})", quiet=quiet)
            summary["fetched"].append(label)

    # Re-extract JSON if anything changed (or --force)
    if summary["fetched"] or summary["errors"] or args.force:
        if args.dry_run:
            log("Dry-run: skipping JSON re-extraction", quiet=quiet)
        else:
            log("Re-extracting consolidated JSON…", quiet=quiet)
            try:
                subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "extract_data.py")],
                    check=True, capture_output=True, text=True,
                )
                log("JSON re-extracted successfully", quiet=quiet)
            except subprocess.CalledProcessError as e:
                log(f"ERROR extracting JSON: {e.stderr or e.stdout}", quiet=quiet)
                return 2

            # Re-embed JSON into the HTML so the dashboard works on file://
            log("Rebuilding dashboard HTML with embedded data…", quiet=quiet)
            try:
                subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "build_dashboard.py")],
                    check=True, capture_output=True, text=True,
                )
                log("Dashboard rebuilt successfully", quiet=quiet)
            except subprocess.CalledProcessError as e:
                log(f"ERROR rebuilding dashboard: {e.stderr or e.stdout}", quiet=quiet)
                return 4

            # Fetch live tickers so the dashboard shows current rates
            log("Fetching live market rates…", quiet=quiet)
            try:
                subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "fetch_live.py")],
                    check=True, capture_output=True, text=True,
                )
                log("Live rates fetched successfully", quiet=quiet)
                # Re-embed to pick up the new live snapshot
                subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "build_dashboard.py")],
                    check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as e:
                log(f"WARNING live fetch: {e.stderr or e.stdout}", quiet=quiet)
    else:
        log("No data changes — JSON is up to date", quiet=quiet)

    log(
        f"Fetch summary: fetched={len(summary['fetched'])} "
        f"unchanged={len(summary['unchanged'])} errors={len(summary['errors'])}",
        quiet=quiet,
    )
    return 0 if not summary["errors"] else 3


if __name__ == "__main__":
    sys.exit(main())