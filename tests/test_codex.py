"""CodexClient against a stubbed `codex exec`: command, isolation checks, failures. No CLI runs."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hjr.client import TransportError
from hjr.codex import (
    DISABLED_FEATURES,
    CodexClient,
    HarnessViolation,
    QuotaExhausted,
    parse_events,
    render_prompt,
    run_with_tree_kill,
    schema_valid,
)
from hjr.config import load_judge_config
from hjr.ratelimit import TokenBucket

ARM = load_judge_config().model("strong")
REPLY = {
    "verdict": "done",
    "reason": "All requirements are met.",
    "wait_on_session": None,
    "wait_on_pid": None,
    "wait_for_seconds": None,
}
MESSAGES = [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}]


def _events(*extra: dict, model: str | None = None) -> str:
    rows = [{"type": "thread.started", "thread_id": "th-1"}, *extra]
    rows.append(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1500,
                "cached_input_tokens": 1024,
                "output_tokens": 80,
                "reasoning_output_tokens": 60,
            },
        }
    )
    if model:
        rows[0]["model"] = model
    return "\n".join(json.dumps(r) for r in rows)


def _error(message: str) -> str:
    return json.dumps({"type": "error", "message": message})


class FakeCodex:
    """Plays `codex exec`: writes the last message where -o points, returns scripted results."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, cmd, *, input, **kwargs):
        self.calls.append({"cmd": cmd, "input": input, "env": kwargs.get("env")})
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        code, stdout, reply, touch = out
        cwd = Path(cmd[cmd.index("--cd") + 1])
        if touch:
            (cwd / "notes.txt").write_text("x")
        if reply is not None:
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text(reply, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")


OK = (0, _events(), json.dumps(REPLY), False)


def _client(outcomes, max_attempts=3):
    fake = FakeCodex(outcomes)
    sleeps = []
    client = CodexClient(
        ARM,
        version="0.159.3",
        limiter=TokenBucket(6000, burst=100),
        run=fake,
        sleep=sleeps.append,
        max_attempts=max_attempts,
        check_version=False,
        executable="codex",
    )
    return client, fake, sleeps


def test_command_pins_model_effort_sandbox_and_disables_tools():
    client, fake, _ = _client([OK])
    client.complete(MESSAGES)
    cmd = fake.calls[0]["cmd"]
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"):
        assert flag in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("--model") + 1] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="medium"' in cmd and 'web_search="disabled"' in cmd
    disabled = {cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"}
    assert disabled == set(DISABLED_FEATURES) and {"shell_tool", "unified_exec"} <= disabled
    assert cmd[-1] == "-"
    assert fake.calls[0]["input"] == "SYSTEM\n\nUSER"


def test_each_call_gets_its_own_empty_directory():
    client, fake, _ = _client([OK, OK])
    client.complete(MESSAGES)
    client.complete(MESSAGES)
    dirs = [c["cmd"][c["cmd"].index("--cd") + 1] for c in fake.calls]
    assert dirs[0] != dirs[1]
    assert not any(Path(d).exists() for d in dirs)


def test_success_records_usage_session_and_schema_validity():
    client, _, _ = _client([(0, _events(model="gpt-6.1-sol"), json.dumps(REPLY), False)])
    res = client.complete(MESSAGES)
    assert json.loads(res.text)["verdict"] == "done"
    assert (res.model_reported, res.provider_reported) == ("gpt-6.1-sol", "codex-cli 0.159.3")
    usage = (res.tokens_in, res.cached_tokens, res.tokens_out, res.reasoning_tokens)
    assert usage == (1500, 1024, 80, 60)
    assert res.cost_usd is None
    assert res.meta["thread_id"] == "th-1" and res.meta["schema_valid"] == "true"


def test_malformed_reply_is_returned_once_and_flagged_not_retried():
    client, fake, _ = _client([(0, _events(), "I think it is done.", False)])
    res = client.complete(MESSAGES)
    assert res.text == "I think it is done." and res.meta["schema_valid"] == "false"
    assert len(fake.calls) == 1


def test_tool_use_halts_the_arm():
    tool = {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}}
    client, fake, _ = _client([(0, _events(tool), json.dumps(REPLY), False), OK])
    with pytest.raises(HarnessViolation):
        client.complete(MESSAGES)
    with pytest.raises(HarnessViolation):
        client.complete(MESSAGES)
    assert len(fake.calls) == 1


def test_files_left_in_the_working_directory_halt_the_arm():
    client, _, _ = _client([(0, _events(), json.dumps(REPLY), True)])
    with pytest.raises(HarnessViolation):
        client.complete(MESSAGES)


def test_rate_limit_is_retried_with_backoff():
    limited = (1, _error("429 Too Many Requests"), None, False)
    client, _, sleeps = _client([limited, OK])
    res = client.complete(MESSAGES)
    assert [a.ok for a in res.attempts] == [False, True]
    assert res.attempts[0].error_type == "rate_limited" and sleeps == [30.0]


def test_usage_limit_halts_without_retrying():
    quota = (1, _error("You have hit your usage limit"), None, False)
    client, fake, _ = _client([quota])
    with pytest.raises(QuotaExhausted):
        client.complete(MESSAGES)
    with pytest.raises(QuotaExhausted):
        client.complete(MESSAGES)
    assert len(fake.calls) == 1


def test_timeouts_are_retried_then_reported_as_transport_failures():
    timeout = subprocess.TimeoutExpired("codex", 900)
    client, _, _ = _client([timeout, timeout], max_attempts=2)
    with pytest.raises(TransportError) as info:
        client.complete(MESSAGES)
    assert [a.error_type for a in info.value.attempts] == ["timeout", "timeout"]


def test_unknown_cli_error_is_not_retried():
    bad = (2, _error("unknown model"), None, False)
    client, fake, _ = _client([bad, bad])
    with pytest.raises(TransportError):
        client.complete(MESSAGES)
    assert len(fake.calls) == 1


def test_version_mismatch_is_refused(monkeypatch):
    monkeypatch.setattr("hjr.codex.installed_version", lambda exe: "0.160.0")
    with pytest.raises(RuntimeError, match="pinned to 0.159.3"):
        CodexClient(ARM, version="0.159.3", limiter=TokenBucket(60, burst=1), executable="codex")


@pytest.mark.parametrize(
    "text, ok",
    [
        (json.dumps(REPLY), True),
        (json.dumps({**REPLY, "verdict": "wait", "wait_for_seconds": 600}), True),
        (json.dumps({"verdict": "done", "reason": "x"}), False),
        (json.dumps({**REPLY, "extra": 1}), False),
        (json.dumps({**REPLY, "verdict": "finished"}), False),
        (json.dumps({**REPLY, "wait_on_pid": True}), False),
        ("prefix " + json.dumps(REPLY), False),
    ],
)
def test_schema_validity(text, ok):
    assert schema_valid(text) is ok


def test_render_prompt_puts_static_instructions_first():
    assert render_prompt(MESSAGES).startswith("SYSTEM")


def test_parse_events_ignores_noise_and_collects_errors():
    out = parse_events('warning: x\n{"type": "turn.failed", "error": {"message": "boom"}}\n{bad')
    assert out["errors"] == ["boom"] and out["tools"] == []


def test_timeout_kills_the_whole_process_tree():
    # A launcher whose child keeps the output pipes open, as `codex` -> node -> codex.exe does.
    child = "import time; time.sleep(120)"
    launcher = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(120)"
    )
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_with_tree_kill([sys.executable, "-c", launcher], input="", timeout=2, text=True)
    assert time.monotonic() - start < 30


def test_run_with_tree_kill_returns_output():
    done = run_with_tree_kill(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        input="verdict",
        timeout=30,
        text=True,
    )
    assert done.returncode == 0 and done.stdout.strip() == "VERDICT"


def test_max_concurrent_caps_calls_in_flight():
    import threading

    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    fake = FakeCodex([OK] * 12)

    def run(cmd, **kwargs):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
            return fake(cmd, **kwargs)

    client = CodexClient(
        ARM,
        version="0.159.3",
        limiter=TokenBucket(6000, burst=100),
        run=run,
        check_version=False,
        executable="codex",
        max_concurrent=4,
    )
    threads = [
        threading.Thread(target=client.complete, args=([{"role": "user", "content": "x"}],))
        for _ in range(12)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["peak"] == 4


def test_codex_endpoint_runs_at_most_twelve_calls_at_once():
    cfg = load_judge_config()
    assert cfg.endpoint(cfg.model("strong")).max_concurrent == 12
