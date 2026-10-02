"""Blind human truth labels for Phase-1 boundaries (prereg amendment "Phase 2 design").

For each boundary, in a seeded order (dev first; held-out only after tag `repair-freeze-v1`):

1. **Blind.** The annotator sees the goal, the tool calls the agent made with their outputs, and
   the workspace at the boundary against the task's seed workspace. Every message the agent wrote
   (its final response included), the verifier, the in-loop judge, and the task, category and
   arm names are hidden. Labels: done, not_done, blocked or ambiguous, with sure/unsure.
2. **Adjudicated.** Committing the blind label reveals the agent's messages and the verifier's
   per-requirement result. The annotator records a final label and whether the verifier was right.

A later **relabel** pass shows 25 seeded boundaries blind again, at least a day after their first
blind label and without it, for intra-rater agreement.

Labels are appended to one JSONL file and never edited; quitting at any prompt loses nothing
already committed. Views and extracted workspaces are written under `private/labelling/`,
named by a hash so the folder name gives nothing away.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import random
import subprocess
import tarfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hjr import stats
from hjr.config import ROOT
from hjr.phase2 import Plan
from hjr.schemas import BoundaryRecord, LabelRecord, read_jsonl

JOBS = ROOT / "jobs"
TASKS = ROOT / "tasks"
WORKDIR = ROOT / "private" / "labelling"
LABELS = ("done", "not_done", "blocked", "ambiguous")
KEYS = {"d": "done", "n": "not_done", "b": "blocked", "a": "ambiguous"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
MAX_FILE_LINES = 400
MAX_FILE_CHARS = 20000
# Files older than the agent's run (by snapshot file time, with this margin) came with the
# task image; when the local seed lacks them they are listed, not shown.
RUN_START_MARGIN_S = 120
MAX_ARG_CHARS = 4000
MAX_OUTPUT_CHARS = 4000


# ── Order ─────────────────────────────────────────────────────────────


def build_order(boundaries: Iterable[BoundaryRecord], seed: str) -> dict[str, list[str]]:
    """Dev then held-out, each shuffled with its own seeded generator from sorted ids."""
    out = {}
    for split in ("dev", "heldout"):
        ids = sorted(b.boundary_id for b in boundaries if b.split == split)
        random.Random(f"{seed}:{split}").shuffle(ids)
        out[split] = ids
    return out


def load_or_write_order(path: Path, boundaries: Sequence[BoundaryRecord], seed: str) -> list[str]:
    order = build_order(boundaries, seed)
    record = {"seed": seed, **order}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved != record:
            raise RuntimeError(f"{path} does not match the order regenerated from seed {seed}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return order["dev"] + order["heldout"]


def heldout_unlocked(tag: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


# ── Sources ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Sources:
    trial_dir: Path
    snapshot: Path
    seed_workspace: Path | None


def sources(b: BoundaryRecord, jobs: Path = JOBS, tasks: Path = TASKS) -> Sources:
    trial_dir = jobs / b.run_id / str(b.tags["trial"])
    snap_name = b.boundary_id.rsplit("/", 1)[1] + ".tgz"
    snapshot = trial_dir / "artifacts" / "logs" / "artifacts" / "boundaries" / snap_name
    if not snapshot.exists():
        raise FileNotFoundError(f"snapshot missing: {snapshot}")
    seed = tasks / b.task_id.split("/", 1)[1] / "environment" / "workspace"
    has_seed = seed.is_dir() and any(seed.iterdir())
    return Sources(trial_dir, snapshot, seed if has_seed else None)


def item_dir(boundary_id: str, root: Path = WORKDIR) -> Path:
    return root / hashlib.sha256(boundary_id.encode("utf-8")).hexdigest()[:12]


def extract(snapshot: Path, dest: Path) -> Path:
    if not dest.exists():
        tmp = dest.with_name(dest.name + ".partial")
        tmp.mkdir(parents=True, exist_ok=True)
        with tarfile.open(snapshot) as tar:
            tar.extractall(tmp, filter="data")
        tmp.rename(dest)
    return dest


# ── Rendering ─────────────────────────────────────────────────────────


def _files(root: Path | None) -> dict[str, Path]:
    if root is None:
        return {}
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not (set(rel.parts[:-1]) & SKIP_DIRS):
            out[rel.as_posix()] = p
    return out


def _text(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def _clip(lines: list[str]) -> list[str]:
    out, chars = [], 0
    for n, line in enumerate(lines):
        if n >= MAX_FILE_LINES or chars + len(line) > MAX_FILE_CHARS:
            rest = len(lines) - n
            return out + [f"… {rest} more lines not shown ({len(lines)} in all)"]
        out.append(line)
        chars += len(line) + 1
    return out


def _fence(lines: list[str], lang: str = "") -> list[str]:
    return [f"````{lang}", *lines, "````"]


def run_start(b: BoundaryRecord) -> float:
    """Epoch seconds a little before the agent's run on this boundary began."""
    seconds = float(b.tags.get("agent_seconds", 0) or 0)
    return b.ts.timestamp() - seconds - RUN_START_MARGIN_S


def workspace_diff(seed: Path | None, ws: Path, started: float | None = None) -> list[str]:
    """Markdown: every file added, removed or changed between seed and boundary workspace.

    A file missing from the local seed but older than the agent's run came with the task image
    (generated data, an upstream repository); it is listed with its size, not shown.
    """
    before, after = _files(seed), _files(ws)
    out, preexisting = [], []
    if seed is None:
        out.append("_The seed workspace is built from the task image and is not available here._")
    for rel in sorted(before.keys() | after.keys()):
        a, b = before.get(rel), after.get(rel)
        if a and b and a.read_bytes() == b.read_bytes():
            continue
        if a is None and started is not None and b.stat().st_mtime < started:
            preexisting.append(f"- `{rel}` ({b.stat().st_size} bytes)")
            continue
        status = "added" if a is None else "removed" if b is None else "changed"
        out += ["", f"#### `{rel}` ({status})", ""]
        if b is None:
            continue
        new = _text(b)
        if new is None:
            out.append(f"_binary, {b.stat().st_size} bytes, sha256 {_sha(b.read_bytes())[:16]}_")
            continue
        old = _text(a) if a else None
        if status == "changed" and old is not None:
            diff = difflib.unified_diff(old, new, "seed", "boundary", lineterm="", n=3)
            out += _fence(_clip(list(diff)), "diff")
        else:
            out += _fence(_clip(new))
    if not out:
        out.append("_No file differs from the seed workspace._")
    if preexisting:
        out += [
            "",
            f"#### {len(preexisting)} files from the task image, unchanged since before the run",
            "",
            "Not in the local seed; their file times predate the agent's run. Open the "
            "workspace to read them.",
            "",
            *preexisting,
        ]
    return out


def git_state(ws: Path) -> list[str]:
    repos = sorted({p.parent for p in ws.rglob(".git") if p.is_dir()})
    out = []
    for repo in repos:
        rel = repo.relative_to(ws).as_posix() or "."
        out += ["", f"#### Git repository `{rel}`", ""]
        for args in (
            ["status", "--short", "--branch"],
            ["log", "--oneline", "--graph", "--all", "-n", "30"],
            ["reflog", "-n", "20"],
        ):
            proc = subprocess.run(
                ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            out += [f"`git {' '.join(args)}`", *_fence((proc.stdout or proc.stderr).splitlines())]
    return out


def _steps(trial_dir: Path, turn: int) -> list[dict]:
    """Trajectory steps up to the end of the given turn (a turn starts at a user step)."""
    doc = json.loads((trial_dir / "agent" / "trajectory.json").read_text(encoding="utf-8"))
    out, users = [], 0
    for step in doc["steps"]:
        if step.get("source") == "user":
            users += 1
            if users > turn:
                break
        out.append(step)
    return out


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… {len(text) - limit} more chars"


def tool_log(trial_dir: Path, turn: int) -> list[str]:
    """Tool calls and their outputs only. Agent-written messages are never included."""
    out = []
    n = 0
    for step in _steps(trial_dir, turn):
        if step.get("source") != "agent":
            continue
        results = {
            r.get("source_call_id"): r.get("content", "")
            for r in (step.get("observation") or {}).get("results", [])
        }
        for call in step.get("tool_calls") or []:
            n += 1
            args = json.dumps(call.get("arguments"), ensure_ascii=False, indent=1)
            result = results.get(call.get("tool_call_id"), "")
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            out += ["", f"#### {n}. `{call.get('function_name')}`", ""]
            out += _fence(_cut(args, MAX_ARG_CHARS).splitlines(), "json")
            out += ["Output:", *_fence(_cut(result, MAX_OUTPUT_CHARS).splitlines())]
    return out or ["_No tool calls._"]


def agent_messages(trial_dir: Path, turn: int) -> list[str]:
    out = []
    for step in _steps(trial_dir, turn):
        msg = step.get("message") or ""
        if step.get("source") == "agent" and msg and msg != "[tool call]":
            out += ["", f"_Step {step.get('step_id')}:_", "", msg]
    return out or ["_The agent wrote no messages._"]


def render_blind(b: BoundaryRecord, src: Sources, ws: Path, position: str) -> str:
    lines = [
        f"# Boundary {position} (blind)",
        "",
        "Hidden: the agent's own messages, the verifier, the judge, the task and the arm.",
        "",
        "## Goal",
        "",
        *_fence(b.goal.splitlines()),
        "",
        f"## Tool calls ({b.turn} turn{'s' if b.turn != 1 else ''})",
        *tool_log(src.trial_dir, b.turn or 1),
        "",
        "## Workspace at the boundary, against the seed",
        "",
        f"Extracted at `{ws.as_posix()}`.",
        *workspace_diff(src.seed_workspace, ws, run_start(b)),
        *git_state(ws),
    ]
    return "\n".join(lines) + "\n"


def render_reveal(b: BoundaryRecord, src: Sources, blind: LabelRecord) -> str:
    reqs = b.verifier.requirements
    lines = [
        f"# Revealed: `{b.boundary_id}`",
        "",
        f"Task `{b.task_id}` ({b.category}, {b.split}). Your blind label: **{blind.label}** "
        f"({blind.confidence}).",
        "",
        f"## Verifier: {b.verifier.truth_state}",
        "",
        *[f"- {'PASS' if ok else 'FAIL'} `{name}`" for name, ok in reqs.items()],
        "",
        "## The agent's messages",
        *agent_messages(src.trial_dir, b.turn or 1),
    ]
    return "\n".join(lines) + "\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── State ─────────────────────────────────────────────────────────────


def load_labels(path: Path) -> list[LabelRecord]:
    return list(read_jsonl(path, LabelRecord)) if path.exists() else []


def append(path: Path, rec: LabelRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(rec.model_dump_json(exclude_none=True) + "\n")


def first_blind(labels: Iterable[LabelRecord]) -> dict[str, LabelRecord]:
    out: dict[str, LabelRecord] = {}
    for r in labels:
        if r.stage == "blind" and r.boundary_id not in out:
            out[r.boundary_id] = r
    return out


def pending(order: Sequence[str], labels: Sequence[LabelRecord]) -> list[tuple[str, str]]:
    """(boundary id, next stage) for every boundary not yet adjudicated, in order."""
    blind = {r.boundary_id for r in labels if r.stage == "blind"}
    done = {r.boundary_id for r in labels if r.stage == "adjudicated"}
    return [(b, "adjudicated" if b in blind else "blind") for b in order if b not in done]


def draw_relabel(plan: Plan, order: Sequence[str]) -> list[str]:
    return random.Random(plan.seed("relabel")).sample(sorted(order), plan.relabel_n)


def relabel_due(
    ids: Sequence[str], labels: Sequence[LabelRecord], now: datetime, min_hours: float
) -> tuple[list[str], list[str]]:
    """(due now, waiting): relabels not yet given, split by time since the first blind label."""
    first = first_blind(labels)
    given = {r.boundary_id for r in labels if r.stage == "relabel"}
    due, waiting = [], []
    for bid in ids:
        if bid in given:
            continue
        ready = now - first[bid].ts >= timedelta(hours=min_hours)
        (due if ready else waiting).append(bid)
    return due, waiting


# ── Prompts ───────────────────────────────────────────────────────────


class Quit(Exception):
    pass


@dataclass
class Console:
    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print
    open: Callable[[Path], None] = lambda p: None

    def choose(self, prompt: str, keys: dict[str, str], default: str | None = None) -> str:
        while True:
            raw = self.ask(prompt).strip().lower()
            if raw == "q":
                raise Quit
            if not raw and default is not None:
                return default
            if raw in keys:
                return keys[raw]
            self.say(f"  choose one of: {', '.join(keys)} (q quits)")

    def text(self, prompt: str, required: bool) -> str:
        while True:
            raw = self.ask(prompt).strip()
            if raw.lower() == "q":
                raise Quit
            if raw or not required:
                return raw
            self.say("  a note is required here")


def _label_prompt(console: Console, view: Path, ws: Path) -> str:
    keys = {**KEYS, "o": "open", "w": "workspace"}
    while True:
        choice = console.choose(
            "  label [d]one [n]ot done [b]locked [a]mbiguous, [o]pen view, [w]orkspace, [q]uit: ",
            keys,
        )
        if choice == "open":
            console.open(view)
        elif choice == "workspace":
            console.open(ws)
        else:
            return choice


def _confidence(console: Console) -> str:
    return console.choose("  confidence [s]ure [u]nsure: ", {"s": "sure", "u": "unsure"})


@dataclass(frozen=True)
class Session:
    plan: Plan
    boundaries: dict[str, BoundaryRecord]
    order: list[str]
    labels_path: Path
    annotator: str
    workdir: Path = WORKDIR
    jobs: Path = JOBS
    tasks: Path = TASKS

    def prepare(self, bid: str) -> tuple[BoundaryRecord, Sources, Path, Path]:
        b = self.boundaries[bid]
        src = sources(b, self.jobs, self.tasks)
        d = item_dir(bid, self.workdir)
        ws = extract(src.snapshot, d / "workspace")
        return b, src, d, ws

    def blind_view(self, bid: str, position: str) -> tuple[Path, Path, str]:
        b, src, d, ws = self.prepare(bid)
        text = render_blind(b, src, ws, position)
        view = d / "blind.md"
        view.write_text(text, encoding="utf-8", newline="\n")
        return view, ws, _sha(text.encode("utf-8"))

    def record(self, bid: str, stage: str, label: str, confidence: str, sha: str, **extra):
        rec = LabelRecord(
            boundary_id=bid,
            stage=stage,
            label=label,
            confidence=confidence,
            order_index=self.order.index(bid),
            view_sha256=sha,
            annotator=self.annotator,
            ts=datetime.now(UTC),
            **extra,
        )
        append(self.labels_path, rec)
        return rec


def label_blind(s: Session, console: Console, bid: str, position: str) -> LabelRecord:
    view, ws, sha = s.blind_view(bid, position)
    console.say(f"\n[{position}] blind view: {view}\n  workspace: {ws}")
    console.open(view)
    label = _label_prompt(console, view, ws)
    confidence = _confidence(console)
    notes = console.text("  notes: ", required=label == "ambiguous" or confidence == "unsure")
    return s.record(bid, "blind", label, confidence, sha, notes=notes)


def adjudicate(s: Session, console: Console, bid: str, blind: LabelRecord) -> LabelRecord:
    b, src, d, ws = s.prepare(bid)
    text = render_reveal(b, src, blind)
    view = d / "reveal.md"
    view.write_text(text, encoding="utf-8", newline="\n")
    console.say(f"  revealed: {view}\n  verifier says {b.verifier.truth_state}")
    console.open(view)
    label = console.choose(
        f"  final label [d/n/b/a] (enter keeps {blind.label}): ", KEYS, default=blind.label
    )
    confidence = _confidence(console)
    verifier_ok = console.choose(
        "  verifier correct? [y]es [n]o [x] not applicable: ", {"y": "yes", "n": "no", "x": "na"}
    )
    notes = console.text(
        "  notes: ",
        required=label != blind.label
        or label == "ambiguous"
        or confidence == "unsure"
        or verifier_ok == "no",
    )
    return s.record(
        bid,
        "adjudicated",
        label,
        confidence,
        _sha(text.encode("utf-8")),
        verifier_correct=verifier_ok,
        notes=notes,
    )


def run_first_pass(s: Session, console: Console, heldout_open: bool) -> int:
    """Label until done, quit, or the held-out gate. Returns how many boundaries were finished."""
    finished = 0
    labels = load_labels(s.labels_path)
    todo = pending(s.order, labels)
    total = len(s.order)
    try:
        for bid, stage in todo:
            if s.boundaries[bid].split == "heldout" and not heldout_open:
                console.say(
                    f"\nDev boundaries are done. Held-out ones open once tag "
                    f"`{s.plan.heldout_after_tag}` exists."
                )
                return finished
            position = f"{s.order.index(bid) + 1}/{total}"
            if stage == "blind":
                blind = label_blind(s, console, bid, position)
            else:
                blind = first_blind(load_labels(s.labels_path))[bid]
                console.say(f"\n[{position}] resuming at adjudication")
            adjudicate(s, console, bid, blind)
            finished += 1
    except Quit:
        console.say("\nStopped. Everything committed so far is saved.")
        return finished
    console.say("\nFirst pass complete.")
    return finished


def run_relabel(s: Session, console: Console, ids: Sequence[str], now: datetime) -> int:
    labels = load_labels(s.labels_path)
    due, waiting = relabel_due(ids, labels, now, s.plan.relabel_min_hours)
    if waiting:
        first = first_blind(labels)
        ready = min(first[b].ts for b in waiting) + timedelta(hours=s.plan.relabel_min_hours)
        console.say(
            f"{len(waiting)} relabels wait for the 24-hour gap; next at {ready:%Y-%m-%d %H:%M} UTC"
        )
    n = 0
    try:
        for k, bid in enumerate(due, start=1):
            view, ws, sha = s.blind_view(bid, f"relabel {k}/{len(due)}")
            console.say(f"\n[relabel {k}/{len(due)}] blind view: {view}")
            console.open(view)
            label = _label_prompt(console, view, ws)
            confidence = _confidence(console)
            notes = console.text("  notes: ", required=label == "ambiguous")
            s.record(bid, "relabel", label, confidence, sha, notes=notes)
            n += 1
    except Quit:
        console.say("\nStopped. Everything committed so far is saved.")
    return n


# ── Report ────────────────────────────────────────────────────────────


def report(
    boundaries: dict[str, BoundaryRecord], labels: Sequence[LabelRecord], relabel_ids: Sequence[str]
) -> str:
    final: dict[str, LabelRecord] = {}
    for r in labels:
        if r.stage == "adjudicated":
            final[r.boundary_id] = r
    blind = first_blind(labels)
    relabels = {r.boundary_id: r for r in labels if r.stage == "relabel"}
    lines = [
        "# Truth labels",
        "",
        f"{len(blind)} blind and {len(final)} adjudicated of {len(boundaries)} boundaries; "
        f"{len(relabels)} of {len(relabel_ids)} relabels.",
        "",
        "## Adjudicated label against the verifier",
        "",
        "| Arm | Split | Verifier \\ Label | " + " | ".join(LABELS) + " |",
        "|---|---|---|" + "---|" * len(LABELS),
    ]
    table: dict[tuple[str, str, str], dict[str, int]] = {}
    for bid, rec in final.items():
        b = boundaries[bid]
        key = (str(b.tags.get("agent_arm", "")), b.split, b.verifier.truth_state)
        table.setdefault(key, dict.fromkeys(LABELS, 0))[rec.label] += 1
    for (arm, split, truth), row in sorted(table.items()):
        lines.append(
            f"| {arm} | {split} | {truth} | " + " | ".join(str(row[x]) for x in LABELS) + " |"
        )
    changed = sum(blind[b].label != r.label for b, r in final.items() if b in blind)
    wrong = sum(r.verifier_correct == "no" for r in final.values())
    lines += [
        "",
        f"Blind label changed at adjudication: {changed}. Verifier judged wrong: {wrong}.",
        "",
        "## Intra-rater agreement (first blind label against blind relabel)",
        "",
    ]
    pairs = [(blind[b].label, r.label) for b, r in relabels.items() if b in blind]
    a = stats.agreement(pairs, LABELS)
    if a.n:
        lines.append(
            f"n = {a.n}: raw agreement {a.observed:.2f}, Cohen's κ "
            f"{'–' if a.kappa is None else f'{a.kappa:.2f}'}, PABAK {a.pabak:.2f}; prevalence "
            + ", ".join(f"{k} {v:.2f}" for k, v in a.prevalence.items())
            + ". One annotator: this is intra-rater, not inter-rater, agreement."
        )
    else:
        lines.append("No relabels yet.")
    amb = sorted(b for b, r in final.items() if r.label == "ambiguous")
    if amb:
        lines += ["", "## Ambiguous (excluded from primary truth)", ""]
        lines += [f"- `{b}`: {final[b].notes}" for b in amb]
    return "\n".join(lines) + "\n"
