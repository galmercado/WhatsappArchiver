"""PII-free logging: scrub JIDs, phone numbers, keys, tokens and filenames.

Defence in depth: code should never log sensitive values in the first place; this
filter is the backstop for anything (including exception text) that slips through.
"""

from __future__ import annotations

import logging
import re

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+\-]+@(?:s\.whatsapp\.net|g\.us|lid|broadcast|c\.us)", re.I), "<jid>"),
    (re.compile(r"\b[0-9a-fA-F]{64}\b"), "<key>"),
    (
        re.compile(r"(?i)\b(?:bearer|token|session|secret|passphrase|password)\b[=: ]+\S+"),
        "<secret>",
    ),
    (
        re.compile(
            r"[^\s/\\'\"]+\.(?:jpe?g|png|webp|gif|opus|ogg|mp3|m4a|aac|amr|mp4|3gp|pdf|docx?|"
            r"xlsx?|pptx?|zip|vcf|txt|db|crypt1\d)\b",
            re.I,
        ),
        "<file>",
    ),
    (re.compile(r"\+?\d[\d ().\-]{6,}\d"), "<num>"),
)


def scrub(text: str) -> str:
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs the rendered message and any attached traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


class RedactingFormatter(logging.Formatter):
    def formatException(self, ei: object) -> str:
        return scrub(super().formatException(ei))  # type: ignore[arg-type]


def configure_logging(verbose: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
