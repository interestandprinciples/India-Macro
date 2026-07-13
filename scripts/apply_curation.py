#!/usr/bin/env python3
"""
Apply a saved curation.json and rebuild the dashboard.

Usage:
  python3 scripts/apply_curation.py [path/to/curation.json]

If no path is given, reads ./data/curation.json (the default).
After applying, rebuilds the dashboard HTML.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
DEFAULT_CURATION = BASE_DIR / "data" / "curation.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default=str(DEFAULT_CURATION),
                    help="Path to curation.json (default: data/curation.json)")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="Don't rebuild the dashboard after applying")
    args = ap.parse_args()

    src = Path(args.path)
    if not src.exists():
        print(f"ERROR: {src} does not exist", file=sys.stderr)
        return 1

    curation = json.loads(src.read_text(encoding="utf-8"))
    # Validate basic shape
    if not isinstance(curation, dict):
        print("ERROR: curation root must be a JSON object", file=sys.stderr)
        return 2
    if "default" not in curation:
        curation["default"] = {"show": True, "mode": "both"}
    if "series" not in curation:
        curation["series"] = {}
    if "themeDefaults" not in curation:
        curation["themeDefaults"] = {}

    DEFAULT_CURATION.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CURATION.write_text(json.dumps(curation, indent=2), encoding="utf-8")
    n_series = len(curation["series"])
    n_themes = len(curation["themeDefaults"])
    print(f"Applied curation to {DEFAULT_CURATION}")
    print(f"  Per-series overrides: {n_series}")
    print(f"  Theme defaults:        {n_themes}")
    print(f"  Default mode:          {curation['default'].get('mode','both')}")

    if not args.no_rebuild:
        print("Rebuilding dashboard…")
        subprocess.run([sys.executable, str(SCRIPT_DIR / "build_dashboard.py")], check=True)

    print("Done. Reload the dashboard to see changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())