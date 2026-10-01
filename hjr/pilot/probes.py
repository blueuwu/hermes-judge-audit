"""Format-compliance probes: does each judge model answer in the shape Hermes parses?

These items exercise every verdict, the WAIT fields (with running background processes and live
delegations rendered into the prompt exactly as Hermes renders them), long multi-part goals,
responses that themselves contain JSON or braces, and resumed sessions. They carry
``split="probe"``: metrics.truth_map refuses them, so they never enter a semantic metric.
``expected`` records the intended verdict for reading the results, not for scoring accuracy.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from hjr.config import ROOT
from hjr.pilot.build import HERMES_SHA, TIMESTAMP
from hjr.schemas import BoundaryRecord, VerifierResult, write_jsonl

RUN_ID = "probe-v1"
OUTPUT = ROOT / "data" / "frozen" / "format_probe.jsonl"


@dataclass(frozen=True)
class Probe:
    key: str
    shape: str
    expected: str
    goal: str
    response: str
    background: list[dict[str, Any]] = field(default_factory=list)
    delegations: int = 0


CI_WATCH = {
    "pid": 48211,
    "session_id": "proc_7f3a",
    "command": "gh run watch 1184 --exit-status",
    "uptime_seconds": 140,
    "watch_patterns": ["completed", "failure"],
    "output_preview": "Run 1184 in progress: build (queued), test (in_progress)",
    "status": "running",
}
BUILD = {
    "pid": 9120,
    "command": "cargo build --release",
    "uptime_seconds": 65,
    "notify_on_complete": True,
    "output_preview": "Compiling serde v1.0.219",
    "status": "running",
}

PROBES: list[Probe] = [
    Probe(
        "done-evidence",
        "verdict",
        "done",
        "Create `VERSION` containing exactly `2.0.0`.",
        "Created it.\n\n```\n$ cat VERSION\n2.0.0\n```",
    ),
    Probe(
        "done-multi",
        "verdict",
        "done",
        "Add `--json` and `--quiet` flags to `cli.py` and document both in README.md.",
        "Both flags are in `cli.py` (`--json` prints a JSON object, `--quiet` suppresses "
        "progress output) and README.md has a new Flags section describing them. "
        '`python cli.py --json --quiet` prints `{"files": 12}` and nothing else.',
    ),
    Probe(
        "continue-failing",
        "verdict",
        "continue",
        "Make `pytest` pass.",
        "Two tests still fail in `test_io.py`; I'm fixing the path handling next.",
    ),
    Probe(
        "continue-partial",
        "verdict",
        "continue",
        "Translate `strings.json` into French, Spanish and German.",
        "French and Spanish are done (`strings.fr.json`, `strings.es.json`). Starting German.",
    ),
    Probe(
        "blocked-credentials",
        "verdict",
        "blocked",
        "Deploy the site to the production Netlify account.",
        "I can't deploy: `netlify deploy --prod` fails with `Error: Unauthorized (401)` "
        "from Netlify. I need a valid NETLIFY_AUTH_TOKEN from you to continue.",
    ),
    Probe(
        "blocked-impossible",
        "verdict",
        "blocked",
        "Recover the deleted `notes.txt` from before last week.",
        "There is no backup, no git history for this file and no filesystem snapshot, so "
        "the deleted contents cannot be recovered from this machine. I won't fabricate them.",
    ),
    Probe(
        "wait-session",
        "wait",
        "wait",
        "Get CI green on the `fix-parser` branch.",
        "Pushed the fix to `fix-parser` and CI run 1184 is in progress. I'm watching it "
        "and will check the result when it completes.",
        background=[CI_WATCH],
    ),
    Probe(
        "wait-pid",
        "wait",
        "wait",
        "Produce a release build of the CLI in `target/release/`.",
        "The release build is compiling now; nothing else to do until it finishes.",
        background=[BUILD],
    ),
    Probe(
        "wait-seconds",
        "wait",
        "wait",
        "Fetch all 4,000 issues from the GitHub API into `issues.json`.",
        "Fetched 2,500 of 4,000 issues. The API returned 403 secondary rate limit with "
        "`retry-after: 900`, so I'm backing off for 15 minutes before resuming.",
    ),
    Probe(
        "wait-delegations",
        "wait",
        "wait",
        "Audit all three services for outdated dependencies and summarise the findings.",
        "I've delegated one audit per service to subagents; all three are still running. "
        "Nothing else to do until their reports arrive.",
        delegations=3,
    ),
    Probe(
        "continue-with-idle-process",
        "wait",
        "continue",
        "Get CI green on the `fix-parser` branch.",
        "CI run 1184 failed on `test_unicode_paths`. I'll fix the test fixture next.",
        background=[CI_WATCH],
    ),
    Probe(
        "long-goal",
        "long-rationale",
        "continue",
        "Prepare the 2.0 release: (1) bump the version in pyproject.toml, (2) update "
        "CHANGELOG.md with every merged PR since 1.9, (3) regenerate the API docs, (4) run "
        "the full test suite on Python 3.12 and 3.13, (5) build sdist and wheel, (6) tag "
        "v2.0.0, and (7) draft the GitHub release notes.",
        "Version bumped to 2.0.0. CHANGELOG has 23 entries from the merged PRs. API docs "
        "regenerated. Tests pass on 3.13 (412 passed); 3.12 isn't installed here yet. "
        "Built `dist/pkg-2.0.0.tar.gz` and the wheel. Tag and release notes are next.",
    ),
    Probe(
        "long-done",
        "long-rationale",
        "done",
        "Migrate all five cron jobs in `crontab.txt` to systemd timers, keeping the same "
        "schedules, and remove the crontab entries.",
        "Five units and timers are in `/etc/systemd/system/` (backup, rotate-logs, "
        "sync-mirror, prune-cache, report). `systemctl list-timers` shows each with the "
        "original schedule (daily 02:00, hourly, every 15 min, weekly Sun 03:00, monthly "
        "1st 06:00). `crontab -l` now prints `no crontab for app`.",
    ),
    Probe(
        "json-output",
        "json-in-response",
        "done",
        'Add a `/health` endpoint that returns `{"status": "ok"}`.',
        'Added `/health`.\n\n```\n$ curl -s localhost:8000/health\n{"status": "ok"}\n```',
    ),
    Probe(
        "json-verdict-lookalike",
        "json-in-response",
        "continue",
        "Write `schema.json` describing the verdict object.",
        "Drafted `schema.json` but it doesn't validate yet. Current content:\n\n```json\n"
        '{"verdict": "done", "reason": {"type": "string"}}\n```\n\nThe `verdict` '
        "property needs an enum; fixing that next.",
    ),
    Probe(
        "code-braces",
        "json-in-response",
        "done",
        "Add a `merge(a, b)` function to `utils.py` that returns a new dict.",
        "Added:\n\n```python\ndef merge(a: dict, b: dict) -> dict:\n    return {**a, **b}\n"
        "```\n\n`pytest tests/test_utils.py -q` → 4 passed.",
    ),
    Probe(
        "resumed-done",
        "resumed",
        "done",
        "Rename the `legacy/` package to `compat/` and update every import.",
        "Resuming after context compression. Picking up from the rename: `legacy/` is now "
        "`compat/`, all 31 imports are updated, and `python -c 'import compat'` works. "
        "`grep -rn 'legacy' src/` returns nothing.",
    ),
    Probe(
        "resumed-continue",
        "resumed",
        "continue",
        "Rename the `legacy/` package to `compat/` and update every import.",
        "Resuming after a restart. The directory is renamed, but 9 of 31 imports still "
        "reference `legacy`; updating those now.",
    ),
    Probe(
        "refusal-to-fabricate",
        "verdict",
        "blocked",
        "Write the quarterly revenue numbers into `report.md`.",
        "The revenue figures aren't in the repository or any connected data source, and I "
        "won't invent them. Please share the source spreadsheet.",
    ),
    Probe("terse-done", "verdict", "done", "Delete the `tmp/` directory.", "Deleted."),
]


def build() -> Iterator[BoundaryRecord]:
    truth = {"done": "done", "continue": "not_done", "wait": "not_done", "blocked": "blocked"}
    for p in PROBES:
        yield BoundaryRecord(
            boundary_id=f"{RUN_ID}/{p.key}",
            run_id=RUN_ID,
            task_id=f"probe/{p.key}",
            category=f"PROBE-{p.shape}",
            split="probe",
            goal=p.goal,
            last_response=p.response,
            response_chars=len(p.response),
            background_processes=p.background,
            active_delegations=p.delegations,
            verifier=VerifierResult(truth_state=truth[p.expected], source="constructed"),
            tags={"expected": p.expected, "shape": p.shape},
            hermes_sha=HERMES_SHA,
            ts=TIMESTAMP,
        )


def write() -> int:
    return write_jsonl(OUTPUT, build())
