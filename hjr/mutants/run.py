"""Run the frozen mutation suite against the current verifiers.

Each task's oracle base (its reference solution's end state, from the ``oracle-suite`` Harbor
job) must first grade done (an infeasible task: blocked with exactly its infeasible
requirements false). A task whose base fails is reported and none of its mutants run.

Output: ``results/mutants/<suite>-<UTC time>.jsonl``, one record per mutant, and a ``.md``
kill table next to it.
"""

from __future__ import annotations

import ast
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hjr import verifier
from hjr.config import ROOT
from hjr.mutants import DATA, Mutant, load_all, outcome, require_frozen, retired

BASES = DATA / "bases.json"
RESULTS = ROOT / "results" / "mutants"
JOBS = ROOT / "jobs"


def infeasible(task: str, tasks: Path = verifier.TASKS) -> tuple[str, ...]:
    """INFEASIBLE from the task's check_state.py, read without importing it."""
    tree = ast.parse((tasks / task / "tests" / "check_state.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "INFEASIBLE" for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    return ()


def load_bases(path: Path = BASES) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


def base_dir(task: str, bases: dict[str, dict[str, str]]) -> Path:
    path = ROOT / bases[task]["source"]
    if not path.is_dir():
        raise SystemExit(f"{task}: base {path} is missing (jobs/ is not committed)")
    return path


def _copy(src: Path, dest: Path) -> Path:
    shutil.copytree(src, dest, symlinks=True)
    return dest


def check_versions(tasks: Iterable[str]) -> dict[str, tuple[str, str]]:
    """Each task's (version, sha); refuse if a verifier changed without a version bump."""
    out = {}
    for task in tasks:
        version, sha = verifier.version_of(task)
        now = verifier.tests_sha(task)
        if now != sha:
            raise SystemExit(f"{task}: tests/ changed but data/verifiers.json still says {version}")
        out[task] = (version, sha)
    return out


@dataclass
class BaseResult:
    task: str
    ok: bool
    truth: str | None
    failing: list[str]
    error: str = ""


def grade_base(task: str, bases: dict) -> BaseResult:
    src = base_dir(task, bases)
    want = bases[task]["tree_sha256"]
    if verifier.tree_sha(src) != want:
        return BaseResult(task, False, None, [], "base tree changed since bases.json")
    (g,) = verifier.grade_snapshots(task, [verifier.snapshot_tgz(src)])
    if not g.ok:
        return BaseResult(task, False, None, [], g.error)
    failing = sorted(k for k, v in g.requirements.items() if not v)
    inf = infeasible(task)
    ok = failing == sorted(inf) and g.truth_state == ("blocked" if inf else "done")
    return BaseResult(task, ok, g.truth_state, failing)


def _expected(m: Mutant, inf: tuple[str, ...]) -> str:
    if m.kind == "benign":
        return "blocked, only " + ",".join(inf) + " false" if inf else "done"
    if m.kind == "req":
        return ("blocked" if inf else "not_done") + f"; {m.breaks[0]} false"
    if inf:
        return "blocked; " + ",".join(m.breaks) + " false"
    return "not done"


def run_task(
    task: str, mutants: list[Mutant], bases: dict, version: tuple[str, str], suite: str
) -> list[dict]:
    inf = infeasible(task)
    src = base_dir(task, bases)
    rows, snaps, graded = [], [], []
    with tempfile.TemporaryDirectory(prefix=f"hjr-{task[:5]}-") as tmp:
        for i, m in enumerate(mutants):
            ws = _copy(src, Path(tmp) / str(i))
            row = {
                "task": task,
                "mutant": m.id,
                "kind": m.kind,
                "doc": m.doc,
                "breaks": list(m.breaks),
                "expected": _expected(m, inf),
                "verifier_version": version[0],
                "verifier_sha256": version[1],
                "suite_sha256": suite,
            }
            try:
                m.apply(ws)
                if verifier.tree_sha(ws) == bases[task]["tree_sha256"]:
                    raise AssertionError("the mutant left the base unchanged")
                snaps.append(verifier.snapshot_tgz(ws))
                graded.append(row)
            except Exception as e:  # a mutant that does not apply is itself an error
                row |= {"outcome": "error" if m.kind == "benign" else "survived_error"}
                row |= {"error": f"apply: {type(e).__name__}: {e}"}
            rows.append(row)
            shutil.rmtree(ws, ignore_errors=True)
    for row, g in zip(graded, verifier.grade_snapshots(task, snaps), strict=True):
        m = next(x for x in mutants if x.id == row["mutant"])
        if not g.ok:
            row |= {"outcome": "error" if m.kind == "benign" else "survived_error"}
            row |= {"error": f"grade: {g.error}"}
            continue
        result, collateral = outcome(m, g.truth_state, g.requirements, inf)
        row |= {
            "actual": g.truth_state,
            "actual_requirements": g.requirements,
            "outcome": result,
            "collateral": collateral,
        }
    return rows


def run(
    tasks: list[str] | None = None, workers: int = 4
) -> tuple[Path, list[BaseResult], list[dict]]:
    suite = require_frozen()
    registry = load_all()
    gone = retired()
    by_task: dict[str, list[Mutant]] = defaultdict(list)
    for key, m in sorted(registry.items()):
        if key not in gone:
            by_task[m.task].append(m)
    bases = load_bases()
    names = sorted(tasks or bases)
    versions = check_versions(names)
    with ThreadPoolExecutor(workers) as pool:
        base_results = list(pool.map(lambda t: grade_base(t, bases), names))
    ready = [b.task for b in base_results if b.ok]
    with ThreadPoolExecutor(workers) as pool:
        chunks = pool.map(lambda t: run_task(t, by_task[t], bases, versions[t], suite), ready)
        rows = [r for chunk in chunks for r in chunk]
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{suite[:12]}-{stamp}.jsonl"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    out.with_suffix(".md").write_text(
        render(suite, base_results, rows), encoding="utf-8", newline="\n"
    )
    return out, base_results, rows


def _failing(row: dict) -> str:
    return ", ".join(sorted(k for k, v in row["actual_requirements"].items() if not v)) or "-"


def render(suite: str, bases: list[BaseResult], rows: list[dict]) -> str:
    lines = [
        "# Mutation suite run",
        "",
        f"Suite `{suite[:12]}`; {len(rows)} mutants on {len({r['task'] for r in rows})} tasks.",
        "",
        "## Base precondition",
        "",
    ]
    bad = [b for b in bases if not b.ok]
    lines.append(f"{len(bases) - len(bad)} of {len(bases)} oracle bases grade as expected.")
    for b in bad:
        lines.append(f"- **{b.task}**: truth {b.truth}, failing {b.failing or '-'} {b.error[:300]}")
    lines += [
        "",
        "## Kill table",
        "",
        "| Task | req | look | con | benign accepted | survived (verdict / error) |",
        "|---|---|---|---|---|---|",
    ]
    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_task[r["task"]].append(r)
    total = Counter()
    for task in sorted(by_task):
        rs = by_task[task]
        cells = []
        for kind in ("req", "look", "con"):
            ks = [r for r in rs if r["kind"] == kind]
            killed = sum(r["outcome"] == "killed" for r in ks)
            total[kind, "killed"] += killed
            total[kind, "n"] += len(ks)
            cells.append(f"{killed}/{len(ks)}" if ks else "–")
        bs = [r for r in rs if r["kind"] == "benign"]
        acc = sum(r["outcome"] == "accepted" for r in bs)
        total["benign", "killed"] += acc
        total["benign", "n"] += len(bs)
        sv = sum(r["outcome"] == "survived_verdict" for r in rs)
        se = sum(r["outcome"] == "survived_error" for r in rs)
        total["sv"] += sv
        total["se"] += se
        lines.append(f"| {task} | {' | '.join(cells)} | {acc}/{len(bs)} | {sv} / {se} |")
    agg = [f"{total[k, 'killed']}/{total[k, 'n']}" for k in ("req", "look", "con", "benign")]
    lines.append(f"| **all** | {' | '.join(agg)} | {total['sv']} / {total['se']} |")
    survivors = [r for r in rows if r["outcome"] in ("survived_verdict", "survived_error")]
    lines += ["", f"## Survivors ({len(survivors)})", ""]
    for r in survivors:
        detail = (
            r.get("error", "")[:200]
            if r["outcome"] == "survived_error"
            else f"graded {r['actual']}, failing {_failing(r)}"
        )
        lines.append(
            f"- `{r['task']}` `{r['mutant']}` ({r['outcome']}): {r['doc']}. "
            f"Expected {r['expected']}; {detail}"
        )
    rejected = [r for r in rows if r["kind"] == "benign" and r["outcome"] != "accepted"]
    lines += ["", f"## Benign variants not accepted ({len(rejected)})", ""]
    for r in rejected:
        detail = r.get("error", "")[:200] or f"graded {r['actual']}, failing {_failing(r)}"
        lines.append(f"- `{r['task']}` `{r['mutant']}`: {r['doc']}. {detail}")
    coll = [r for r in rows if r.get("collateral")]
    lines += ["", f"## Collateral ({len(coll)} req mutants also failed other requirements)", ""]
    for r in coll:
        lines.append(f"- `{r['task']}` `{r['mutant']}`: also {', '.join(r['collateral'])}")
    return "\n".join(lines) + "\n"


# ── Apply-only check (no grading) ─────────────────────────────────────


def apply_check() -> list[str]:
    """Apply every mutant to a copy of its base and confirm it changes the tree. No verifier
    runs, so this can be done before the freeze without tuning mutants to verdicts."""
    bases = load_bases()
    problems = []
    for key, m in sorted(load_all().items()):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _copy(base_dir(m.task, bases), Path(tmp) / "app")
            try:
                m.apply(ws)
                if verifier.tree_sha(ws) == bases[m.task]["tree_sha256"]:
                    problems.append(f"{key}: no change")
            except Exception as e:
                problems.append(f"{key}: {type(e).__name__}: {e}")
    return problems
