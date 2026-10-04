"""Small workspace edits the mutants are written with. Each fails loudly when its target is
missing, so a mutant that no longer applies shows up as an error, never as a silent no-op."""

from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path


def read(ws: Path, rel: str) -> str:
    return (ws / rel).read_text(encoding="utf-8")


def write(ws: Path, rel: str, text: str) -> None:
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def replace(ws: Path, rel: str, old: str, new: str, count: int = 1) -> None:
    """Replace the first ``count`` occurrences (0: all); the text must occur at least once."""
    text = read(ws, rel)
    if old not in text:
        raise AssertionError(f"{rel}: {old!r} not found")
    write(ws, rel, text.replace(old, new) if count == 0 else text.replace(old, new, count))


def append(ws: Path, rel: str, text: str) -> None:
    write(ws, rel, read(ws, rel) + text)


def delete(ws: Path, rel: str) -> None:
    path = ws / rel
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
    else:
        raise AssertionError(f"{rel}: not found")


def load_json(ws: Path, rel: str):
    return json.loads(read(ws, rel))


def dump_json(ws: Path, rel: str, obj, indent: int | None = 2) -> None:
    write(ws, rel, json.dumps(obj, indent=indent) + "\n")


def edit_json(ws: Path, rel: str, fn: Callable) -> None:
    """Load, pass to ``fn`` (which edits in place or returns a new value), and write back."""
    obj = load_json(ws, rel)
    new = fn(obj)
    dump_json(ws, rel, obj if new is None else new)


def read_csv(ws: Path, rel: str) -> list[list[str]]:
    with (ws / rel).open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def write_csv(ws: Path, rel: str, rows: list[list[str]]) -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    write(ws, rel, buf.getvalue())


def sql(ws: Path, rel: str, script: str) -> None:
    if not (ws / rel).is_file():
        raise AssertionError(f"{rel}: not found")
    con = sqlite3.connect(ws / rel)
    try:
        con.executescript(script)
        con.commit()
    finally:
        con.close()
