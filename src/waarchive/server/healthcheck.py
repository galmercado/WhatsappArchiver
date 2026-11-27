"""Container HEALTHCHECK: GET /healthz on localhost with the configured Host header."""

from __future__ import annotations

import http.client
import os
import sys
from urllib.parse import urlsplit


def main() -> int:
    port = int(os.environ.get("WA_PORT", "8000"))
    host = urlsplit(os.environ.get("WA_BASE_URL", "http://localhost")).hostname or "localhost"
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/healthz", headers={"Host": host})
        ok = conn.getresponse().status == 200
        conn.close()
    except (OSError, http.client.HTTPException):
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
