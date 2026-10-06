"""Launch-environment checks run before a paid Harbor job (deviation-1).

Harbor 0.23.0 reads the Hermes session log with ``Path.read_text()`` and no encoding. On a
Windows code page that read fails on UTF-8 session bytes and the error kills the whole job, so
a job may launch only with Python's UTF-8 mode on (``PYTHONUTF8=1``).
"""

from __future__ import annotations

import codecs
import locale
import sys


def utf8_problems(utf8_mode: int, preferred_encoding: str) -> list[str]:
    """Why this interpreter would decode text files as anything but UTF-8; empty when fine."""
    problems = []
    if utf8_mode != 1:
        problems.append(f"sys.flags.utf8_mode is {utf8_mode}, need 1 (set PYTHONUTF8=1)")
    # Python spells it 'utf-8' in UTF-8 mode, so compare codec names, not raw strings
    if codecs.lookup(preferred_encoding).name != "utf-8":
        problems.append(f"locale.getpreferredencoding() is {preferred_encoding!r}, need UTF-8")
    return problems


def check_utf8() -> list[str]:
    return utf8_problems(sys.flags.utf8_mode, locale.getpreferredencoding())
