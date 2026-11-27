"""`python -m waarchive.server` — local debug or container entry point."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from ..logsafe import configure_logging
from .settings import ConfigError, Settings


def main() -> int:
    ap = argparse.ArgumentParser(prog="waarchive.server")
    ap.add_argument("--reload", action="store_true", help="hot reload (dev only)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    configure_logging(args.verbose)
    try:
        s = Settings.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if args.reload and s.env != "dev":
        print("--reload is only allowed in dev", file=sys.stderr)
        return 2
    uvicorn.run(
        "waarchive.server.app:create_app_from_env", factory=True, host=s.host, port=s.port,
        reload=args.reload, access_log=False, server_header=False, proxy_headers=False,
        log_config=None,
    )  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
