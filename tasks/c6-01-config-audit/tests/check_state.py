"""Per-requirement state checks for hjr/c6-01-config-audit. Reads only the workspace.

One requirement per config file: the file must parse and equal the fixed config exactly,
so a missed violation and a change to a valid value both fail that file.
"""

import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def check(ws: Path) -> dict[str, bool]:
    return {name: _load(ws / "configs" / f"{name}.json") == want for name, want in EXPECTED.items()}
