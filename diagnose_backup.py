#!/usr/bin/env python3
"""Thin launcher: `python diagnose_backup.py --help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from waarchive.ingest.diagnose import main

if __name__ == "__main__":
    sys.exit(main())
