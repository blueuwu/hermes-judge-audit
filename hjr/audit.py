"""Single-pass verifier QA (prereg Amendment 1); records never replace primary truth.

Truth, for the strata and in the view, is primary truth: the regrade of each arm's frozen
boundaries at the frozen verifier (``hjr regrade``, ``data/truth/``), not the v1 truth stored
in the boundary records."""

from __future__ import annotations

import difflib
import hashlib
import json
import random
import subprocess
import tarfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from hjr import regrade, stats
from hjr.config import ROOT
from hjr.phase2 import cell_of
from hjr.schemas import BoundaryRecord, VerifierResult, read_jsonl

CELL = "prod-plain:self:head4k"
HELDOUT_TAG = "repair-freeze-v1"
JOBS = ROOT / "jobs"
TASKS = ROOT / "tasks"
WORKDIR = ROOT / "private" / "audit"
DRAW = ROOT / "data" / "audit" / "draw.json"
RECORDS = ROOT / "data" / "audit" / "records.jsonl"
CAPS = {"A": 20, "B": 30, "C": 10}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
MAX_FILE_LINES = 400
MAX_FILE_CHARS = 20000
RUN_START_MARGIN_S = 120


class AuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary_id: str
    split: Literal["dev", "heldout"]
    agent_arm: Literal["weak", "strong"]
    verifier: VerifierResult
    verifier_sha256: str


def metadata(doc: dict, primary: dict[str, dict]) -> AuditItem | None:
    # Project before validation so malformed held-out payloads cannot appear in exceptions.
    run = doc.get("run_id")
    if run not in {"phase1-weak", "phase1-strong"}:
        return None
    if doc.get("tags", {}).get("phase", "1a") != "1a":
        return None
    row = primary.get(doc["boundary_id"])
    if row is None:
        raise ValueError("a Phase 1a boundary has no primary truth row")
    return AuditItem(
        boundary_id=doc["boundary_id"],
        split=doc["split"],
        agent_arm=run.removeprefix("phase1-"),
        verifier={"truth_state": row["truth_state"], "source": "verifier"},
        verifier_sha256=_digest(row),
    )


def load_metadata(paths: Sequence[Path]) -> dict[str, AuditItem]:
    items = {}
    for path in paths:
        primary = regrade.primary_rows(path)
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                item = metadata(json.loads(line), primary)
                if item is not None:
                    if item.boundary_id in items:
                        raise ValueError("duplicate Phase 1a boundary id")
                    items[item.boundary_id] = item
    return items


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(doc: dict) -> str:
    return _sha(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def draw(
    items: dict[str, AuditItem], verdict_paths: Sequence[Path], *, seed: int, primary_verifier: str
) -> dict:
    """Sample globally across both arms using effective production-cell decisions."""
    if not primary_verifier.strip():
        raise ValueError("primary verifier freeze identifier is required")
    votes: dict[str, dict[int, str]] = {bid: {} for bid in items}
    identities: dict[str, dict[str, set[str]]] = {}
    for path in verdict_paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                doc = json.loads(line)
                bid = doc["boundary_id"]
                if bid not in items or cell_of(doc["variant"]) != CELL:
                    continue
                arm = items[bid].agent_arm
                if doc["variant"] != f"prod-plain:self-{arm}:head4k":
                    raise ValueError("production self judge belongs to another agent arm")
                sample = doc["sample"]
                if type(sample) is not int or sample not in range(3) or sample in votes[bid]:
                    raise ValueError("duplicate or unexpected production sample")
                decision = doc["decision"]
                if decision not in {"done", "continue", "blocked"}:
                    raise ValueError("invalid effective decision")
                votes[bid][sample] = decision
                ids = identities.setdefault(arm, {"arm": set(), "sub_arm": set()})
                ids["arm"].add(doc["arm_id"])
                # Empty responses skip the call and have no provider-reported identity.
                if doc.get("outcome") != "no_call":
                    ids["sub_arm"].add(doc["sub_arm_id"])
    if any(len(v) != 3 for v in votes.values()):
        raise ValueError("audit draw needs all three production samples for every Phase 1a item")
    if any(len(ids["arm"]) != 1 or len(ids["sub_arm"]) > 1 for ids in identities.values()):
        raise ValueError("cannot pool production judge identities within an agent arm")
    pools: dict[str, list[str]] = {s: [] for s in CAPS}
    for bid, item in sorted(items.items()):
        verifier_done = item.verifier.truth_state == "done"
        judge_done = sum(v == "done" for v in votes[bid].values()) >= 2
        s = "A" if verifier_done != judge_done else "B" if verifier_done else "C"
        pools[s].append(bid)
    strata = {}
    for s, pool in pools.items():
        size = min(CAPS[s], len(pool))
        rng = random.Random(f"{seed}:audit-{s.lower()}")
        picked = pool[:] if size == len(pool) else rng.sample(pool, size)
        strata[s] = {
            "population": pool,
            "sample": sorted(picked),
            "inclusion_probability": size / len(pool) if pool else None,
        }
    return {
        "version": 1,
        "seed": seed,
        "cell": CELL,
        "samples": 3,
        "primary_verifier": primary_verifier,
        "items": {bid: item.model_dump() for bid, item in sorted(items.items())},
        "judge_sha256": _digest(
            {
                "votes": votes,
                "identities": {
                    arm: {key: sorted(values) for key, values in ids.items()}
                    for arm, ids in identities.items()
                },
            }
        ),
        "strata": strata,
    }


def load_or_write_draw(path: Path, expected: dict) -> dict:
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved != expected:
            raise ValueError("saved audit draw differs from seed or inputs; refusing to redraw")
        return saved
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    return expected


def heldout_unlocked() -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{HELDOUT_TAG}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def require_open(split: str) -> None:
    if split == "heldout" and not heldout_unlocked():
        raise PermissionError(f"held-out audit requires tag {HELDOUT_TAG}")


@dataclass(frozen=True)
class Sources:
    trial_dir: Path
    snapshot: Path
    seed_workspace: Path | None


def sources(b: BoundaryRecord, jobs: Path = JOBS, tasks: Path = TASKS) -> Sources:
    require_open(b.split)
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


def render_blind(b: BoundaryRecord, src: Sources, ws: Path, position: str) -> str:
    require_open(b.split)
    lines = [
        f"# Audit {position}",
        "",
        "## Goal",
        "",
        *_fence(b.goal.splitlines()),
        "",
        "## Trajectory",
        "",
    ]
    for step in _steps(src.trial_dir, b.turn or 1):
        lines += [f"### Step {step.get('step_id')} ({step.get('source')})", ""]
        if msg := step.get("message"):
            lines += _fence(str(msg).splitlines())
        for call in step.get("tool_calls") or []:
            lines += _fence(json.dumps(call, ensure_ascii=False, indent=2).splitlines(), "json")
        if observation := step.get("observation"):
            lines += _fence(
                json.dumps(observation, ensure_ascii=False, indent=2).splitlines(), "json"
            )
    lines += [
        "",
        "## Workspace against the seed",
        "",
        *workspace_diff(src.seed_workspace, ws, run_start(b)),
        *git_state(ws),
        "",
        f"## Verifier: {b.verifier.truth_state}",
        "",
        *[f"- {'PASS' if ok else 'FAIL'} `{name}`" for name, ok in b.verifier.requirements.items()],
    ]
    return "\n".join(lines) + "\n"


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary_id: str
    verifier_correct: Literal["yes", "no"]
    reason: str = ""
    fix: str = ""
    order_index: int
    view_sha256: str
    draw_sha256: str
    primary_verifier: str
    annotator: str
    ts: AwareDatetime

    @model_validator(mode="after")
    def required_reason(self) -> AuditRecord:
        if self.verifier_correct == "no" and not self.reason.strip():
            raise ValueError("a reason is required when the verifier is incorrect")
        if not self.annotator.strip():
            raise ValueError("annotator is required")
        return self


def load_records(path: Path) -> list[AuditRecord]:
    return list(read_jsonl(path, AuditRecord)) if path.exists() else []


def audit_order(draw_log: dict) -> list[str]:
    ids = [bid for s in CAPS for bid in draw_log["strata"][s]["sample"]]
    # Mixing strata in the displayed order avoids disclosing them through blocks of items.
    return sorted(
        ids,
        key=lambda bid: (draw_log["items"][bid]["split"] == "heldout", _sha(bid.encode("utf-8"))),
    )


def checked_records(draw_log: dict, records: Sequence[AuditRecord]) -> dict[str, AuditRecord]:
    order = audit_order(draw_log)
    out = {}
    for rec in records:
        if rec.boundary_id not in order or rec.boundary_id in out:
            raise ValueError("unsampled or duplicate audit record")
        if (
            rec.draw_sha256 != _digest(draw_log)
            or rec.primary_verifier != draw_log["primary_verifier"]
            or rec.order_index != order.index(rec.boundary_id)
        ):
            raise ValueError("audit record provenance does not match the draw")
        out[rec.boundary_id] = rec
    return out


class Quit(Exception):
    pass


@dataclass
class Console:
    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print
    open: Callable[[Path], None] = lambda p: None

    def choose(self, prompt: str, keys: dict[str, str]) -> str:
        while True:
            raw = self.ask(prompt).strip().lower()
            if raw == "q":
                raise Quit
            if raw in keys:
                return keys[raw]
            self.say(f"choose one of: {', '.join(keys)} (q quits)")

    def text(self, prompt: str, required: bool = False) -> str:
        while True:
            raw = self.ask(prompt).strip()
            if raw.lower() == "q":
                raise Quit
            if raw or not required:
                return raw
            self.say("a reason is required here")


@dataclass(frozen=True)
class Session:
    draw_log: dict
    boundary_paths: Sequence[Path]
    records_path: Path
    annotator: str
    workdir: Path = WORKDIR
    jobs: Path = JOBS
    tasks: Path = TASKS

    def boundary(self, bid: str) -> BoundaryRecord:
        if bid not in audit_order(self.draw_log):
            raise ValueError("boundary was not sampled")
        require_open(self.draw_log["items"][bid]["split"])
        found = None
        for path in self.boundary_paths:
            primary = regrade.primary_rows(path)
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    doc = json.loads(line)
                    if doc.get("boundary_id") != bid:
                        continue
                    require_open(doc["split"])
                    item = metadata(doc, primary)
                    if item is None or item.model_dump() != self.draw_log["items"][bid]:
                        raise ValueError("boundary metadata differs from the frozen audit draw")
                    if found is not None:
                        raise ValueError("duplicate sampled boundary")
                    # Suppress validation payloads; they can include controller judge reasons.
                    try:
                        found = BoundaryRecord.model_validate(doc)
                    except ValueError:
                        raise ValueError("invalid sampled boundary record") from None
                    verifier = regrade.primary_verifier(primary[bid])
                    found = found.model_copy(update={"verifier": verifier})
        if found is None:
            raise ValueError("sampled boundary is missing")
        return found

    def blind_view(self, bid: str, position: str) -> tuple[Path, Path, str]:
        b = self.boundary(bid)
        src = sources(b, self.jobs, self.tasks)
        d = item_dir(bid, self.workdir)
        ws = extract(src.snapshot, d / "workspace")
        text = render_blind(b, src, ws, position)
        view = d / "blind.md"
        view.write_text(text, encoding="utf-8", newline="\n")
        return view, ws, _sha(text.encode("utf-8"))

    def record(self, bid: str, correct: str, reason: str, fix: str, sha: str) -> AuditRecord:
        require_open(self.draw_log["items"][bid]["split"])
        existing = checked_records(self.draw_log, load_records(self.records_path))
        if bid in existing:
            raise ValueError("boundary already audited; records are append-only")
        rec = AuditRecord(
            boundary_id=bid,
            verifier_correct=correct,
            reason=reason,
            fix=fix,
            order_index=audit_order(self.draw_log).index(bid),
            view_sha256=sha,
            draw_sha256=_digest(self.draw_log),
            primary_verifier=self.draw_log["primary_verifier"],
            annotator=self.annotator,
            ts=datetime.now(UTC),
        )
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.records_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(rec.model_dump_json() + "\n")
        return rec


def run_pass(s: Session, console: Console) -> int:
    order = audit_order(s.draw_log)
    completed = checked_records(s.draw_log, load_records(s.records_path))
    finished = 0
    try:
        for bid in order:
            if bid in completed:
                continue
            try:
                require_open(s.draw_log["items"][bid]["split"])
            except PermissionError:
                console.say(f"Held-out audit waits for tag {HELDOUT_TAG}.")
                return finished
            position = f"{order.index(bid) + 1}/{len(order)}"
            view, ws, sha = s.blind_view(bid, position)
            console.say(f"\n[{position}] audit view: {view}\nworkspace: {ws}")
            console.open(view)
            while True:
                choice = console.choose(
                    "verifier correct? [y]es [n]o, [o]pen view, [w]orkspace, [q]uit: ",
                    {"y": "yes", "n": "no", "o": "open", "w": "workspace"},
                )
                if choice in {"yes", "no"}:
                    break
                console.open(view if choice == "open" else ws)
            reason = console.text("reason: ", required=choice == "no")
            fix = console.text("fix, if made: ")
            s.record(bid, choice, reason, fix, sha)
            finished += 1
    except Quit:
        console.say("Stopped. Completed audit records are saved; the current item will resume.")
        return finished
    console.say("Audit complete.")
    return finished


def report(draw_log: dict, records: Sequence[AuditRecord]) -> str:
    completed = checked_records(draw_log, records)
    lines = [
        "# Human audit",
        "",
        f"Primary verifier: `{draw_log['primary_verifier']}`.",
        "",
        "| Stratum | Population | Drawn | Audited | Errors | Inclusion probability "
        "| Error rate | Wilson 95% |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for s in CAPS:
        stratum = draw_log["strata"][s]
        got = [completed[bid] for bid in stratum["sample"] if bid in completed]
        n, k = len(got), sum(r.verifier_correct == "no" for r in got)
        ci = stats.wilson(k, n)
        rate = stats.fmt_count(k, n)
        interval = "–" if ci is None else f"[{ci[0]:.4f}, {ci[1]:.4f}]"
        pi = stratum["inclusion_probability"]
        lines.append(
            f"| {s} | {len(stratum['population'])} | {len(stratum['sample'])} | {n} | {k} | "
            f"{'–' if pi is None else f'{pi:.6f}'} | {rate} | {interval} |"
        )
    lines += [
        "",
        "Error rates use audited items only; incomplete samples are provisional.",
        "Counts only below 20 audited items. Wilson bounds are proportions.",
        "C is a check, not a precise estimate. Phase 1b is excluded.",
        "Audit findings do not replace primary truth or change the repair.",
    ]
    return "\n".join(lines) + "\n"
