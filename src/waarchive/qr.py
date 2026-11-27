"""QR codes for the authenticator setup key: terminal rendering (any theme) and an SVG fallback."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TextIO

from .secure_fs import open_private

QUIET = 2  # white border in modules (the QR spec asks for 4; 2 scans fine on phone cameras)


def matrix(data: str) -> list[list[bool]]:
    import qrcode  # noqa: PLC0415
    from qrcode.constants import ERROR_CORRECT_M  # noqa: PLC0415

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return [[bool(c) for c in row] for row in qr.get_matrix()]


def render_ansi(m: list[list[bool]], quiet: int = QUIET) -> str:
    """Black/white blocks drawn with explicit background colours, so it scans on dark and light terminals."""
    black, white, reset = "\x1b[40m  \x1b[0m", "\x1b[47m  \x1b[0m", ""
    width = len(m[0]) + 2 * quiet if m else 0
    blank = white * width + reset
    rows = [blank] * quiet
    rows += [
        white * quiet + "".join(black if c else white for c in row) + white * quiet for row in m
    ]
    rows += [blank] * quiet
    return "\n".join(rows)


def render_plain(m: list[list[bool]], quiet: int = QUIET) -> str:
    """No colours: '##' for dark modules (only scannable on a light background; used as a last resort)."""
    pad = "  " * quiet
    rows = ["  " * (len(m[0]) + 2 * quiet)] * quiet
    rows += [pad + "".join("##" if c else "  " for c in row) + pad for row in m]
    rows += ["  " * (len(m[0]) + 2 * quiet)] * quiet
    return "\n".join(rows)


def ansi_ok(stream: TextIO | None = None) -> bool:
    s = stream or sys.stdout
    if os.environ.get("NO_COLOR") or not getattr(s, "isatty", lambda: False)():
        return False
    return os.name != "nt" or bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))


def write_svg(data: str, path: Path) -> None:
    import qrcode  # noqa: PLC0415
    from qrcode.constants import ERROR_CORRECT_M  # noqa: PLC0415
    from qrcode.image.svg import SvgPathImage  # noqa: PLC0415

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=SvgPathImage)
    with open_private(path) as fh:
        img.save(fh)
