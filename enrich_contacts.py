#!/usr/bin/env python3
"""Thin launcher: `python enrich_contacts.py --help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from waarchive.ingest.enrich_cli import main

if __name__ == "__main__":
    sys.exit(main())
