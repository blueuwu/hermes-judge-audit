"""Read Harbor jobs without imports from the study, writes, or network access.

Rules (one terminal cause per failed/materialized-incomplete trial, in order):
* Harbor: UnicodeDecodeError plus a Harbor traceback frame; or Harbor's explicit
  RewardFileNotFoundError / RewardFileEmptyError. A generic exception with a Harbor
  caller is NOT enough: custom agents and task setup can fail under that caller.
* Timeout: TimeoutError, APITimeoutError, AgentTimeoutError, VerifierTimeoutError,
  EnvironmentTimeoutError; or RuntimeError with the literal "Command timed out"
  and a Harbor Docker frame. A recorded agent_exit_code=null is the hjr harness's
  timeout sentinel (an absent field is not). Timeout takes priority over provider.
* Provider: the named OpenAI SDK error types below, or a terminal Hermes ERROR
  line matching hjr.ingest's marker. A final failed judge attempt is terminal;
  an earlier failed attempt followed by success is not a trial failure.
* Unclassified: any other exception, missing/unreadable trial result, malformed
  diagnostic record, or controller_error without a recognized type/status.
  HTTP 400..599 counts as provider only in judge attempt metadata.

Retries are a separate, overlapping measure, NOT a cause: hjr judge attempt > 1
counts an actual retry invocation, not a retryable flag. Group final attempts by
(boundary_id, variant, sample). Harbor stats.n_retries is reported separately.
No retries are inferred from job names or repeated tasks. Task reward=0 does not
mean infrastructure failure. Scheduled but unmaterialized trials are not failed
trials; they are shown separately. Archived jobs under _aborted are included.

Only result/config JSON, agent judge_attempts.jsonl, agent turns.jsonl, and
agent hermes-logs/*.log are read. No trajectory text, identifiers, paths, or log
excerpts are printed. Counts describe the available snapshot, not unseen runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

TIMEOUT_TYPES = {
    "TimeoutError",
    "APITimeoutError",
    "AgentTimeoutError",
    "VerifierTimeoutError",
    "EnvironmentTimeoutError",
}
PROVIDER_TYPES = {
    "APIError",
    "APIConnectionError",
    "APIStatusError",
    "AuthenticationError",
    "PermissionDeniedError",
    "RateLimitError",
    "InternalServerError",
    "BadRequestError",
    "NotFoundError",
    "UnprocessableEntityError",
}
HARBOR_TYPES = {"RewardFileNotFoundError", "RewardFileEmptyError"}
PROVIDER_MARKER = re.compile(r" ERROR .*(Non-retryable client error|API call failed after)")


def classify_exception(info: dict) -> str:
    """Classify only structured exception fields, never arbitrary agent output."""
    kind = str(info.get("exception_type", "")).rsplit(".", 1)[-1]
    trace = str(info.get("exception_traceback", "")).replace("\\", "/")
    message = str(info.get("exception_message", ""))
    if (kind == "UnicodeDecodeError" and "/harbor/" in trace) or kind in HARBOR_TYPES:
        return "harbor"
    if kind in TIMEOUT_TYPES or (
        kind == "RuntimeError"
        and "Command timed out" in message + trace
        and "/harbor/environments/docker/" in trace
    ):
        return "timeout"
    if kind in PROVIDER_TYPES:
        return "provider"
    return "unclassified"


def classify_attempt(record: dict) -> str:
    kind = str(record.get("error_type", "")).rsplit(".", 1)[-1]
    if kind in TIMEOUT_TYPES:
        return "timeout"
    status = record.get("http_status")
    if kind in PROVIDER_TYPES or (isinstance(status, int) and 400 <= status <= 599):
        return "provider"
    return "unclassified"


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("expected JSON object")
            records.append(record)
    return records


@dataclass
class TrialCounts:
    cause: str | None = None
    retries: int = 0
    unicode_error: bool = False
    missing_result: bool = False
    unreadable: bool = False


def count_trial(trial: Path) -> TrialCounts:
    out = TrialCounts()
    causes = set()
    try:
        if not (trial / "result.json").exists():
            out.missing_result = True
            causes.add("unclassified")
        else:
            info = read_json(trial / "result.json").get("exception_info")
            if info:
                causes.add(classify_exception(info))
                out.unicode_error = (
                    str(info.get("exception_type", "")).rsplit(".", 1)[-1] == "UnicodeDecodeError"
                    and classify_exception(info) == "harbor"
                )
        attempts = read_records(trial / "agent" / "judge_attempts.jsonl")
        final = {}
        for record in attempts:
            n = record.get("attempt", 1)
            if not isinstance(n, int) or n < 1:
                raise ValueError("invalid attempt index")
            out.retries += n > 1
            key = (record.get("boundary_id"), record.get("variant"), record.get("sample"))
            final[key] = record
        for record in final.values():
            if record.get("status") == "error":
                causes.add(classify_attempt(record))
        for record in read_records(trial / "agent" / "turns.jsonl"):
            if "agent_exit_code" in record and record["agent_exit_code"] is None:
                causes.add("timeout")
            if record.get("controller_error") and not any(
                a.get("boundary_id") == record.get("boundary_id") and a.get("status") == "error"
                for a in final.values()
            ):
                causes.add("unclassified")
        for log in sorted((trial / "agent" / "hermes-logs").glob("*.log")):
            if any(
                PROVIDER_MARKER.search(line)
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
            ):
                causes.add("provider")
    except (OSError, ValueError, TypeError, AttributeError):
        out.unreadable = True
        causes.add("unclassified")
    out.cause = next(
        (cause for cause in ("harbor", "timeout", "provider", "unclassified") if cause in causes),
        None,
    )
    return out


@dataclass
class JobCounts:
    name: str
    total: int
    present: int
    causes: Counter = field(default_factory=Counter)
    retry_trials: int = 0
    retry_attempts: int = 0
    harbor_retries: int | None = None
    unicode_errors: int = 0
    missing_results: int = 0
    unreadable_trials: int = 0
    metadata_unreadable: bool = False


def count_job(job: Path) -> JobCounts:
    trials = [
        p
        for p in sorted(job.iterdir())
        if p.is_dir()
        and not p.is_symlink()
        and ((p / "config.json").exists() or (p / "result.json").exists())
    ]
    out = JobCounts(job.name, len(trials), len(trials))
    try:
        data = read_json(job / "result.json")
        total = data.get("n_total_trials")
        if isinstance(total, int) and total >= 0:
            out.total = total
        retries = data.get("stats", {}).get("n_retries")
        if isinstance(retries, int) and retries >= 0:
            out.harbor_retries = retries
    except (OSError, ValueError, TypeError, AttributeError):
        out.metadata_unreadable = True
    for trial in trials:
        counts = count_trial(trial)
        if counts.cause:
            out.causes[counts.cause] += 1
        out.retry_trials += counts.retries > 0
        out.retry_attempts += counts.retries
        out.unicode_errors += counts.unicode_error
        out.missing_results += counts.missing_result
        out.unreadable_trials += counts.unreadable
    return out


def discover_jobs(root: Path) -> list[Path]:
    jobs = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.is_symlink():
            continue
        if path.name == "_aborted":
            jobs.extend(discover_jobs(path))
        elif (path / "config.json").exists() or (path / "result.json").exists():
            jobs.append(path)
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-dir", type=Path, default=Path("jobs"))
    args = parser.parse_args(argv)
    if not args.jobs_dir.is_dir():
        print(
            "jobs/ is missing or not a directory; supply --jobs-dir to an existing jobs root.",
            file=sys.stderr,
        )
        return 2
    print("Terminal causes are exclusive; hjr retries overlap and are not failures by themselves.")
    print("total=scheduled (fallback: present); absent=unmaterialized, not counted as failed.")
    print(
        "job\ttotal\tpresent\tabsent\tfailed\tharbor\tprovider\ttimeout\tunclassified"
        "\thjr_retry_trials\thjr_retry_attempts\tharbor_retries\tunicode"
        "\tmissing_results\tunreadable_trials\tmetadata_unreadable"
    )
    try:
        jobs = discover_jobs(args.jobs_dir)
        for job in jobs:
            c = count_job(job)
            values = [
                c.name,
                c.total,
                c.present,
                max(0, c.total - c.present),
                sum(c.causes.values()),
                *(c.causes[k] for k in ("harbor", "provider", "timeout", "unclassified")),
                c.retry_trials,
                c.retry_attempts,
                c.harbor_retries if c.harbor_retries is not None else "unknown",
                c.unicode_errors,
                c.missing_results,
                c.unreadable_trials,
                int(c.metadata_unreadable),
            ]
            print("\t".join(map(str, values)))
    except OSError:
        print(
            "Could not read jobs; check read permissions. No files were written.", file=sys.stderr
        )
        return 2
    if not jobs:
        print("No Harbor jobs found (expected job directories with config.json or result.json).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
