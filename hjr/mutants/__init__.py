"""Mutation suite for the state verifiers (prereg Amendment 1, "Mutation suite, post hoc").

Every mutant is a function that edits a copy of a task's oracle base (its reference solution's
end state) in place. Kinds, by id prefix:

* ``req:<requirement>[/n]``: breaks exactly that requirement. Killed when the verifier reads it
  false and the truth is not done (``blocked`` on an infeasible task).
* ``look:<name>``: a lookalike wrong solution, from the task's failure hypothesis. Killed when
  the truth is not done; on an infeasible task, when every requirement in ``breaks`` reads false.
* ``con:<name>``: a constraint violation the task actually forbids (tests or inputs it says not
  to touch). Killed as ``look``.
* ``benign:<name>``: an alternative correct solution. Expected done (on an infeasible task:
  blocked with exactly the infeasible requirements false). Reported, never gated.

Kill attribution: every non-benign mutant has targeted checks (``breaks``, or for mutants
frozen without them, ``data/mutants/targets.json``). A kill counts (``killed_targeted``) only
when every targeted check reads false; a not-done verdict reached through other checks is
``killed_collateral``, and one with no targeted check false marks a broken mutant.

Mutants are frozen before their first run: ``data/mutants/suite.json`` records a sha256 of each
mutant's and each helper's source. After that, mutants may be added (and frozen in turn) but
never edited or deleted; a wrong one is retired in ``data/mutants/retired.jsonl`` with a reason.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hjr.config import ROOT

DATA = ROOT / "data" / "mutants"
SUITE = DATA / "suite.json"
TARGETS = DATA / "targets.json"
FAMILIES = ("c1", "c2", "c3", "c4", "c5", "c6")
KINDS = ("req", "look", "con", "benign")


@dataclass(frozen=True)
class Mutant:
    task: str  # task directory name, e.g. c2-01-rename-function
    id: str  # kind:name, unique within the task
    doc: str
    apply: Callable[[Path], None]
    breaks: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.task}/{self.id}"

    @property
    def kind(self) -> str:
        return self.id.split(":", 1)[0]

    @property
    def targets(self) -> tuple[str, ...]:
        """The checks this mutant is meant to break (none for a benign variant)."""
        return self.breaks or tuple(load_targets().get(self.key, ()))

    def source_sha(self) -> str:
        """sha256 of the metadata, the source, and every module-level helper or constant the
        mutant reads (recursively), so editing anything a mutant depends on changes it."""
        meta = json.dumps([self.task, self.id, self.doc, list(self.breaks)])
        deps = _dependencies(self.apply)
        text = meta + "\n" + inspect.getsource(self.apply) + "\n" + json.dumps(deps)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _names(code) -> set[str]:
    out = set(code.co_names)
    for c in code.co_consts:
        if inspect.iscode(c):
            out |= _names(c)
    return out


def _dependencies(fn, seen: set[str] | None = None) -> dict[str, str]:
    """Module globals a function reads: helper functions by source, constants by repr.
    Imported modules are named only; ``ops`` helpers are frozen on their own."""
    seen = set() if seen is None else seen
    out = {}
    for name in sorted(_names(fn.__code__)):
        if name in seen or name not in fn.__globals__:
            continue
        seen.add(name)
        value = fn.__globals__[name]
        if inspect.ismodule(value) or inspect.isclass(value):
            out[name] = f"<{type(value).__name__} {value.__name__}>"
        elif inspect.isfunction(value):
            if value.__module__ == fn.__module__:
                out[name] = inspect.getsource(value)
                out.update(_dependencies(value, seen))
            else:
                out[name] = f"<function {value.__module__}.{value.__qualname__}>"
        else:
            out[name] = repr(value)
    return out


REGISTRY: dict[str, Mutant] = {}


def mutant(task: str, id: str, doc: str, breaks: tuple[str, ...] = ()):
    """Register the decorated function as a mutant of ``task``."""
    kind = id.split(":", 1)[0]
    if kind not in KINDS:
        raise ValueError(f"{task}/{id}: kind must be one of {KINDS}")
    if kind == "req":
        req = id.split(":", 1)[1].split("/", 1)[0]
        breaks = (req,)

    def deco(fn: Callable[[Path], None]) -> Callable[[Path], None]:
        m = Mutant(task, id, doc, fn, tuple(breaks))
        if m.key in REGISTRY:
            raise ValueError(f"duplicate mutant {m.key}")
        REGISTRY[m.key] = m
        return fn

    return deco


def load_all() -> dict[str, Mutant]:
    for fam in FAMILIES:
        importlib.import_module(f"hjr.mutants.{fam}")
    return REGISTRY


def helper_shas() -> dict[str, str]:
    """sha256 of each helper in ``hjr.mutants.ops``; mutants call them, so they freeze too."""
    from hjr.mutants import ops

    out = {}
    for name, fn in inspect.getmembers(ops, inspect.isfunction):
        if fn.__module__ == ops.__name__:
            out[name] = hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()
    return out


def load_targets(path: Path = TARGETS) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["targets"]


SECTIONS = ("mutants", "helpers", "targets")


def current() -> dict[str, dict[str, str]]:
    return {
        "mutants": {k: m.source_sha() for k, m in sorted(load_all().items())},
        "helpers": dict(sorted(helper_shas().items())),
        "targets": {k: json.dumps(v) for k, v in sorted(load_targets().items())},
    }


def suite_hash(entries: dict[str, dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def load_frozen(path: Path = SUITE) -> dict:
    if not path.exists():
        return {"mutants": {}, "helpers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def drift(frozen: dict, now: dict) -> list[str]:
    """Frozen entries that were edited or deleted (never allowed), as messages."""
    out = []
    for section in SECTIONS:
        for key, sha in frozen.get(section, {}).items():
            if key not in now[section]:
                out.append(f"{section[:-1]} {key} was deleted")
            elif now[section][key] != sha:
                out.append(f"{section[:-1]} {key} was edited")
    return out


def unfrozen(frozen: dict, now: dict) -> list[str]:
    return [
        f"{section[:-1]} {key}"
        for section in SECTIONS
        for key in now[section]
        if key not in frozen.get(section, {})
    ]


def freeze(path: Path = SUITE) -> tuple[str, list[str]]:
    """Record new mutants and helpers; refuse if any frozen one changed. Returns (hash, added)."""
    frozen, now = load_frozen(path), current()
    bad = drift(frozen, now)
    if bad:
        raise SystemExit("frozen mutants changed:\n  " + "\n  ".join(bad))
    added = unfrozen(frozen, now)
    entries = {section: now[section] for section in SECTIONS}
    record = {"suite_sha256": suite_hash(entries), **entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    return record["suite_sha256"], added


def require_frozen(path: Path = SUITE) -> str:
    """The frozen suite hash, if the code matches it exactly; otherwise refuse."""
    frozen, now = load_frozen(path), current()
    problems = drift(frozen, now) + [f"{x} is not frozen" for x in unfrozen(frozen, now)]
    if problems:
        raise SystemExit(
            "the mutation suite does not match data/mutants/suite.json "
            "(run `hjr mutants freeze` and commit first):\n  " + "\n  ".join(problems)
        )
    return frozen["suite_sha256"]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()]


def retired(path: Path = DATA / "retired.jsonl") -> dict[str, str]:
    """Retired mutant key -> reason."""
    return {r["mutant"]: r["reason"] for r in read_jsonl(path)}


# ── Kill rule ─────────────────────────────────────────────────────────


def outcome(
    m: Mutant, truth: str | None, reqs: dict[str, bool] | None, infeasible: tuple[str, ...]
) -> tuple[str, list[str]]:
    """(outcome, collateral) for a graded mutant.

    Mutants: killed_targeted | killed_collateral | survived_verdict. Benign variants:
    accepted | rejected. Collateral lists the other requirements that read false (excluding
    infeasible ones).
    """
    assert truth is not None and reqs is not None
    failing = {k for k, v in reqs.items() if not v}
    blocked_task = bool(infeasible)
    if m.kind == "benign":
        ok = failing == set(infeasible) and truth == ("blocked" if blocked_task else "done")
        return ("accepted" if ok else "rejected"), []
    targets = set(m.targets)
    hit = bool(targets) and targets <= failing
    collateral = sorted(failing - targets - set(infeasible))
    if blocked_task:  # truth is always blocked; only the targeted checks can kill
        return ("killed_targeted" if truth == "blocked" and hit else "survived_verdict"), collateral
    wrong = truth == "not_done" if m.kind == "req" else truth != "done"
    if not wrong:
        return "survived_verdict", collateral
    return ("killed_targeted" if hit else "killed_collateral"), collateral


def broken(m: Mutant, reqs: dict[str, bool]) -> bool:
    """A kill with no targeted check false: the mutant does not do what it says."""
    return not any(reqs.get(t) is False for t in m.targets)


NOT_KILLED = ("killed_collateral", "survived_verdict", "survived_error")
