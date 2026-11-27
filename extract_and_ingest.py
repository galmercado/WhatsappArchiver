#!/usr/bin/env python3
"""Thin launcher: `python extract_and_ingest.py --help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from waarchive.ingest.cli import main

if __name__ == "__main__":
    sys.exit(main())
