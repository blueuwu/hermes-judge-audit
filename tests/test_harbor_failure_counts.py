"""Synthetic failure evidence only; these tests never require private jobs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harbor_failure_counts import (
    classify_attempt,
    classify_exception,
    count_job,
    count_trial,
    discover_jobs,
    main,
)


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({"exception_type": "UnicodeDecodeError"}, "unclassified"),
        (
            {
                "exception_type": "UnicodeDecodeError",
                "exception_traceback": 'File "C:\\lib\\harbor\\environments\\docker.py"',
            },
            "harbor",
        ),
        ({"exception_type": "RewardFileNotFoundError"}, "harbor"),
        (
            {"exception_type": "ValueError", "exception_traceback": "/lib/harbor/job.py"},
            "unclassified",
        ),
        ({"exception_type": "FileNotFoundError"}, "unclassified"),
        ({"exception_type": "CancelledError"}, "unclassified"),
        ({"exception_type": "RuntimeError", "exception_message": "timed out"}, "unclassified"),
        (
            {
                "exception_type": "RuntimeError",
                "exception_message": "Command timed out",
                "exception_traceback": "/lib/harbor/environments/docker/docker.py",
            },
            "timeout",
        ),
        ({"exception_type": "asyncio.TimeoutError"}, "timeout"),
        ({"exception_type": "openai.APITimeoutError"}, "timeout"),
        ({"exception_type": "RateLimitError"}, "provider"),
        ({"exception_type": "NotFoundError"}, "provider"),
    ],
)
def test_explicit_exception_rules(info, expected):
    assert classify_exception(info) == expected


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"error_type": "APITimeoutError", "http_status": 504}, "timeout"),
        ({"http_status": 429}, "provider"),
        ({"error_type": "AuthenticationError"}, "provider"),
        ({"error_type": "arbitrary", "http_status": 200}, "unclassified"),
    ],
)
def test_attempt_rules(record, expected):
    assert classify_attempt(record) == expected


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def test_recovered_retry_is_not_failed_trial(tmp_path):
    write_json(tmp_path / "result.json", {"exception_info": None})
    write_records(
        tmp_path / "agent/judge_attempts.jsonl",
        [
            {"boundary_id": "a", "attempt": 1, "status": "error", "error_type": "RateLimitError"},
            {"boundary_id": "a", "attempt": 2, "status": "ok"},
            {"boundary_id": "b", "attempt": 1, "status": "ok"},
        ],
    )
    c = count_trial(tmp_path)
    assert c.cause is None
    assert c.retries == 1


def test_unresolved_provider_and_timeout_precedence(tmp_path):
    write_json(tmp_path / "result.json", {})
    write_records(
        tmp_path / "agent/judge_attempts.jsonl",
        [
            {"boundary_id": "a", "attempt": 1, "status": "error", "error_type": "RateLimitError"},
        ],
    )
    assert count_trial(tmp_path).cause == "provider"
    write_records(tmp_path / "agent/turns.jsonl", [{"agent_exit_code": None}])
    assert count_trial(tmp_path).cause == "timeout"


def test_terminal_marker_only_not_arbitrary_error_text(tmp_path):
    write_json(tmp_path / "result.json", {})
    log = tmp_path / "agent/hermes-logs/runtime.log"
    log.parent.mkdir(parents=True)
    log.write_text(" INFO Non-retryable client error\n", encoding="utf-8")
    assert count_trial(tmp_path).cause is None
    log.write_text(" ERROR Non-retryable client error\n", encoding="utf-8")
    assert count_trial(tmp_path).cause == "provider"


def test_archived_job_and_pending_trials_are_separate(tmp_path):
    job = tmp_path / "_aborted/archived"
    write_json(job / "result.json", {"n_total_trials": 320, "stats": {"n_retries": 0}})
    write_json(job / "started/config.json", {})
    write_json(
        job / "failed/result.json",
        {
            "exception_info": {
                "exception_type": "UnicodeDecodeError",
                "exception_traceback": "/lib/harbor/env.py",
            }
        },
    )
    assert discover_jobs(tmp_path) == [job]
    c = count_job(job)
    assert (c.total, c.present, c.missing_results, c.unicode_errors) == (320, 2, 1, 1)
    assert c.causes == {"harbor": 1, "unclassified": 1}
    assert c.harbor_retries == 0


def test_malformed_record_is_unclassified_and_no_private_text_printed(tmp_path, capsys):
    job = tmp_path / "synthetic"
    write_json(job / "result.json", {"n_total_trials": 1})
    write_json(
        job / "trial/result.json",
        {
            "exception_info": {
                "exception_type": "UnknownError",
                "exception_message": "PRIVATE SENTINEL",
            }
        },
    )
    bad = job / "trial/agent/judge_attempts.jsonl"
    bad.parent.mkdir(parents=True)
    bad.write_text("PRIVATE SENTINEL", encoding="utf-8")
    assert count_trial(job / "trial").unreadable
    assert main(["--jobs-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "PRIVATE SENTINEL" not in output
    assert str(tmp_path) not in output
    assert "synthetic" in output


def test_standalone_missing_jobs_without_site_packages(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/harbor_failure_counts.py"
    result = subprocess.run(
        [sys.executable, "-S", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "jobs/ is missing" in result.stderr
    assert list(tmp_path.iterdir()) == []
