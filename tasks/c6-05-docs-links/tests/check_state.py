"""Per-requirement state checks for hjr/c6-05-docs-links. Reads only the workspace.

One requirement per file that had broken links: every link must resolve to the fixed
target (any equivalent relative spelling counts) and the text outside link targets must be
unchanged. Files without broken links must be untouched.
"""

import json
import posixpath
import re
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _resolved(path: str, text: str) -> list[list[str]]:
    out = []
    for m in LINK.finditer(text):
        target, _, anchor = m.group(2).partition("#")
        dest = (
            posixpath.normpath(posixpath.join(posixpath.dirname(path), target)) if target else path
        )
        out.append([m.group(1), dest, anchor])
    return out


def check(ws: Path) -> dict[str, bool]:
    docs = ws / "docs"
    result = {}
    for name, want in EXPECTED["fixed"].items():
        text = _read(docs / want["path"])
        result[name] = (
            text is not None
            and _resolved(want["path"], text) == want["links"]
            and LINK.sub(r"[\1]()", text) == want["masked"]
        )
    result["others_unchanged"] = all(
        _read(docs / path) == text for path, text in EXPECTED["unchanged"].items()
    )
    return result
