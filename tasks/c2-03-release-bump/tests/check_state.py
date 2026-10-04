"""Per-requirement state checks for hjr/c2-03-release-bump. Reads only the workspace.

v2: "Change nothing else" is checked over the whole file set. Every file must be one the task
started with (byproducts such as __pycache__ and .pytest_cache aside); files outside the
release targets must be byte-identical, and the release targets may differ only where the
release is written (the masked version fields, badge and changelog sections).
"""

import hashlib
import json
import re
import tomllib
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def _assign(src: str, name: str) -> list[str]:
    return re.findall(rf"^{name}\s*=\s*[\"']([^\"']*)[\"']", src, re.M)


def _section(changelog: str, heading: str) -> str | None:
    m = re.search(rf"^## {re.escape(heading)}[ \t]*$(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    return m.group(1) if m else None


def _entries(body: str | None) -> list[str]:
    return [line[2:].strip() for line in (body or "").splitlines() if line.startswith("- ")]


RELEASE_HEADINGS = ("Unreleased", "1.5.0 - 2026-10-02")
BYPRODUCTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
MASKS = {
    "pyproject.toml": [r"^version\s*=.*$"],
    "src/fluxq/__init__.py": [r"^__version__\s*=.*$"],
    "docs/conf.py": [r"^version\s*=.*$", r"^release\s*=.*$"],
    "README.md": [r"badge/version-[0-9A-Za-z.]+-blue"],
}


def _masked(rel: str, text: str) -> str:
    for pattern in MASKS[rel]:
        text = re.sub(pattern, "<release>", text, flags=re.M)
    return text


def _files(ws: Path) -> dict[str, Path]:
    out = {}
    for p in ws.rglob("*"):
        parts = p.relative_to(ws).parts
        if p.is_file() and not set(parts) & BYPRODUCTS and p.suffix != ".pyc":
            out["/".join(parts)] = p
    return out


def _nothing_else_changed(ws: Path, changelog: str, headings: list[str]) -> bool:
    files = _files(ws)
    if sorted(files) != sorted(EXPECTED["files"]):
        return False
    for rel, sha in EXPECTED["files"].items():
        if rel in MASKS:
            if _masked(rel, _read(files[rel])) != EXPECTED["masked"][rel]:
                return False
        elif sha is not None and hashlib.sha256(files[rel].read_bytes()).hexdigest() != sha:
            return False
    # CHANGELOG.md (sha null): the title, the other sections and the history are fixed; the
    # two release sections are checked by changelog_section and unreleased_empty
    return (
        changelog.partition("\n## ")[0] == EXPECTED["changelog_header"]
        and [h for h in headings if h not in RELEASE_HEADINGS] == EXPECTED["history_headings"]
        and changelog.endswith(EXPECTED["changelog_history"])
    )


def check(ws: Path) -> dict[str, bool]:
    try:
        project = tomllib.loads(_read(ws / "pyproject.toml"))["project"]
    except (tomllib.TOMLDecodeError, KeyError):
        project = {}
    conf = _read(ws / "docs/conf.py")
    changelog = _read(ws / "CHANGELOG.md")
    headings = re.findall(r"^## (.+?)[ \t]*$", changelog, re.M)
    return {
        "pyproject_version": project.get("version") == "1.5.0",
        "package_version": _assign(_read(ws / "src/fluxq/__init__.py"), "__version__") == ["1.5.0"],
        "docs_version": _assign(conf, "release") == ["1.5.0"]
        and _assign(conf, "version") == ["1.5"],
        "readme_badge": "badge/version-1.5.0-blue" in _read(ws / "README.md"),
        "changelog_section": _entries(_section(changelog, "1.5.0 - 2026-10-02"))
        == EXPECTED["released_entries"],
        "unreleased_empty": headings[:2] == ["Unreleased", "1.5.0 - 2026-10-02"]
        and _entries(_section(changelog, "Unreleased")) == [],
        # a blind replace of 1.4.2 also rewrites the dependency pin and the history
        "nothing_else_changed": project.get("dependencies") == EXPECTED["dependencies"]
        and "retrylib 1.4.2 or later in the 1.4 series" in _read(ws / "README.md")
        and _nothing_else_changed(ws, changelog, headings),
    }
