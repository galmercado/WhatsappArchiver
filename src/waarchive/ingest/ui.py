"""User interaction abstraction (terminal in production, scripted in tests)."""

from __future__ import annotations

import getpass
import sys
from typing import Protocol

UNROOTED_ALERT = """\
==============================================================================
  !!  DEVICE IS NOT ROOTED  !!
==============================================================================
  Android's app sandbox blocks access to WhatsApp's private data
  (/data/data/com.whatsapp/). Automated extraction of the private key and
  databases is therefore NOT possible on this device.

  This tool will NOT attempt exploits or any root/bootloader tricks.
  WARNING: unlocking a Samsung bootloader triggers a FACTORY WIPE (and trips
  Knox permanently). Do not do that to get at your chats.

  What happens next:
    * Whatever is readable on shared storage (msgstore.db.crypt14/15 and the
      Media/ folder) is pulled now.
    * To decrypt it you need ONE of:
        1) your 64-digit End-to-End Encrypted Backup key
           (WhatsApp > Settings > Chats > Chat backup > End-to-end encrypted
            backup > Turn on > "Use 64-digit encryption key instead"), or
        2) a local folder with a manually exported `key` and/or
           `msgstore.db` / `wa.db`.
==============================================================================
"""


class UI(Protocol):
    def say(self, msg: str) -> None: ...
    def alert(self, msg: str) -> None: ...
    def ask(self, prompt: str) -> str: ...
    def ask_secret(self, prompt: str) -> bytearray: ...


class TerminalUI:
    def say(self, msg: str) -> None:
        print(msg)

    def alert(self, msg: str) -> None:
        print(msg, file=sys.stderr)

    def ask(self, prompt: str) -> str:
        return input(prompt)

    def ask_secret(self, prompt: str) -> bytearray:
        return bytearray(getpass.getpass(prompt).encode("utf-8"))
