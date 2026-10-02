"""Per-requirement state checks for hjr/c6-03-dependency-audit. Reads only the workspace."""

import json
import re
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(\[[^\]]*\])?==(\S+)$")


def _pins(text: str) -> dict[str, str]:
    return {m.group(1): m.group(3) for m in map(PIN.match, text.splitlines()) if m}


def check(ws: Path) -> dict[str, bool]:
    try:
        req = (ws / "requirements.txt").read_text()
    except (OSError, UnicodeDecodeError):
        req = ""
    try:
        audit = json.loads((ws / "out/audit.json").read_text())
    except (OSError, ValueError):
        audit = None
    want_pins = _pins(EXPECTED["requirements"])
    pins = _pins(req)
    upgraded = {a["package"] for a in EXPECTED["audit"]}
    return {
        "affected_upgraded": all(pins.get(p) == want_pins[p] for p in upgraded),
        "unaffected_unchanged": all(
            pins.get(p) == want_pins[p] for p in want_pins if p not in upgraded
        ),
        "file_preserved": req.splitlines() == EXPECTED["requirements"].splitlines(),
        "audit_written": audit == EXPECTED["audit"],
    }
