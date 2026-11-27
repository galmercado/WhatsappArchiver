#!/usr/bin/env python3
"""One-command local launcher (127.0.0.1 only).

    python start_local.py                 # open your archive (./archive by default)
    python start_local.py --demo          # try the app with fake, harmless data first

First run asks you to choose a login password and prints a key for your authenticator app.
Nothing leaves your computer.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import socket
import subprocess  # nosec B404 - fixed argv lists only
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

AUTH_DIR = ROOT / "local-auth"
MIN_PASSWORD = 14


def ensure_auth(
    auth_dir: Path,
    read_secret: Callable[[str], str] = getpass.getpass,
    say: Callable[[str], None] = print,
) -> tuple[str, str]:
    """Return (argon2 password hash, TOTP secret), creating them on first run."""
    import pyotp  # noqa: PLC0415
    from argon2 import PasswordHasher  # noqa: PLC0415

    hash_file, totp_file = auth_dir / "password_hash", auth_dir / "totp_secret"
    if hash_file.is_file() and totp_file.is_file():
        return hash_file.read_text().strip(), totp_file.read_text().strip()

    say("\nFirst-time setup: choose the password you will use to sign in to the app.")
    say(f"(At least {MIN_PASSWORD} characters. This is NOT your WhatsApp or Google password.)")
    password = read_secret("Choose a login password: ")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(
            f"Password too short (needs at least {MIN_PASSWORD} characters). Run again."
        )
    if read_secret("Type it again: ") != password:
        raise SystemExit("The two passwords did not match. Run again.")

    secret = pyotp.random_base32()
    auth_dir.mkdir(mode=0o700, exist_ok=True)
    for path, value in ((hash_file, PasswordHasher().hash(password)), (totp_file, secret)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(value)
    say(
        "\nNow add a 6-digit code generator to your phone (Google Authenticator, Aegis, 2FAS, ...):"
    )
    say("  open the app > add account > 'Enter a setup key' and type:")
    say(f"\n      {secret}\n")
    say("  (name it anything, e.g. 'WhatsApp archive'; type of key: time-based)")
    input("Press Enter once the app shows a 6-digit code that changes every 30 seconds... ")
    return hash_file.read_text().strip(), secret


def ensure_web(root: Path, run: Callable[..., object] = subprocess.run) -> Path:
    """Return web/dist, building the interface once if needed (requires Node.js)."""
    dist = root / "web" / "dist"
    if (dist / "index.html").is_file():
        return dist
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            "The web interface has not been built and Node.js is not installed.\n"
            "Install Node.js 22 from https://nodejs.org (LTS) and run this again."
        )
    print("Building the web interface (one time, takes about a minute)...")
    run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root / "web", check=True)
    run([npm, "run", "build"], cwd=root / "web", check=True)
    return dist


def build_settings(archive: Path, dist: Path, port: int, password_hash: str, totp_secret: str):  # type: ignore[no-untyped-def]
    from waarchive.server.settings import Settings  # noqa: PLC0415

    return Settings(
        env="dev", archive_dir=archive, auth_mode="password_totp", base_url=f"http://localhost:{port}",
        host="127.0.0.1", port=port, password_hash=password_hash, totp_secret=totp_secret, static_dir=dist,
    )  # fmt: skip


def make_demo(dest: Path) -> str:
    """Create a small archive of synthetic (fake) chats so you can try the interface."""
    import tempfile  # noqa: PLC0415

    from archive_factory import PASSPHRASE, make_archive  # noqa: PLC0415

    if dest.exists():
        return PASSPHRASE
    with tempfile.TemporaryDirectory() as tmp:
        built = make_archive(Path(tmp))
        shutil.copytree(built, dest)
    return PASSPHRASE


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Start the archive viewer on this computer only.")
    ap.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "archive",
        help="folder made by extract_and_ingest.py",
    )
    ap.add_argument(
        "--demo", action="store_true", help="use fake demo data instead of your archive"
    )
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    archive = ROOT / "demo-archive" if args.demo else args.archive
    vault_pass: str | None = None
    if args.demo:
        vault_pass = make_demo(archive)
    if not (archive / "archive.db").is_file() or not (archive / "archive.kdf.json").is_file():
        print(
            f"No archive found in '{archive}'.\nCreate one with extract_and_ingest.py (see the tutorial), or try: python start_local.py --demo"
        )
        return 2
    if not port_free(args.port):
        print(
            f"Port {args.port} is already in use. Close the other program or pick another: --port 8001"
        )
        return 2

    password_hash, totp_secret = ensure_auth(AUTH_DIR)
    dist = ensure_web(ROOT)

    import uvicorn  # noqa: PLC0415

    from waarchive.logsafe import configure_logging  # noqa: PLC0415
    from waarchive.server.app import create_app  # noqa: PLC0415

    configure_logging(False)
    settings = build_settings(archive.resolve(), dist, args.port, password_hash, totp_secret)
    url = settings.base_url
    print(
        f"\nOpen {url} in your browser (it only works on this computer). Press Ctrl+C here to stop."
    )
    if vault_pass:
        print(f"DEMO vault passphrase (fake data): {vault_pass}")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        server_header=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
