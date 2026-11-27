"""Generate WA_PASSWORD_HASH / WA_TOTP_SECRET for password+TOTP mode."""

from __future__ import annotations

import getpass
import sys

import pyotp
from argon2 import PasswordHasher


def main() -> int:
    pw = getpass.getpass("Choose a login password (min 14 chars): ")
    if len(pw) < 14 or pw != getpass.getpass("Repeat: "):
        print("password too short or mismatch", file=sys.stderr)
        return 2
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name="archive", issuer_name="WhatsApp Archive")
    h = PasswordHasher().hash(pw)
    print("# add to your .env (in docker-compose env files escape '$' as '$$'):")
    print(f"WA_PASSWORD_HASH={h}")
    print(f"WA_TOTP_SECRET={secret}")
    print(f"\nAdd this to your authenticator app:\n{uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
