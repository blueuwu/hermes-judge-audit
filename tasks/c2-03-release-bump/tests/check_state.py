"""Per-requirement state checks for hjr/c2-03-release-bump. Reads only the workspace."""

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
        and changelog.endswith(EXPECTED["changelog_history"])
        and "retrylib 1.4.2 or later in the 1.4 series" in _read(ws / "README.md"),
    }
