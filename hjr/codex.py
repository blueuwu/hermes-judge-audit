"""Judge calls through the Codex CLI (`codex exec`), for the `strong` judge.

The CLI is an agent harness, not a completion endpoint, so some of what the judge sees and how
it samples cannot be set from here. What is controlled, per call:

* a fresh, empty working directory and a read-only sandbox, with user config and exec rules
  ignored, no session persisted, and every tool-bearing feature disabled;
* the model and reasoning effort, pinned on the command line;
* the CLI version, checked before the first call; any other version is refused;
* a JSON Schema for the final message (the Hermes verdict shapes). The reply is then parsed by
  the same Hermes parser as every other arm, with no retry on a malformed reply. Whether the
  reply matched the schema exactly is recorded in ``harness_meta["schema_valid"]``.

Not controllable, and stated wherever results are reported: the CLI's own system instructions
around the judge prompt, temperature, and max_tokens. The judge prompt (system then user
message, static instructions first) is piped in on stdin as one block.

A call that used any tool, or left anything in its working directory, raises
``HarnessViolation`` and halts the arm: the judge must see only the prompt. Rate limits are
retried with backoff; an exhausted subscription quota halts the arm, and a later rerun of the
resume-safe replay picks up where it stopped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from hjr.arms import Arm
from hjr.client import Attempt, CompletionResult, TransportError
from hjr.ratelimit import TokenBucket
from hjr.replay import ArmHalted

CALL_TIMEOUT_S = 900.0
MAX_ATTEMPTS = 6
BASE_BACKOFF_S = 30.0
MAX_BACKOFF_S = 900.0
# Set to a dedicated CODEX_HOME (logged in once) to keep the owner's skills, plugins and
# memories out of the judge's context. Whether one was used is recorded on every call.
CODEX_HOME_ENV = "HJR_CODEX_HOME"

# Features that give the agent a tool or extra context (`codex features list`, 0.159.3).
DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "code_mode_host",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "plugins",
    "realtime_conversation",
    "remote_plugin",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "sleep_tool",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
)

# The verdict shapes JUDGE_SYSTEM_PROMPT asks for, as a strict schema (every key present,
# wait targets null unless the verdict is wait).
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["done", "blocked", "continue", "wait"]},
        "reason": {"type": "string"},
        "wait_on_session": {"type": ["string", "null"]},
        "wait_on_pid": {"type": ["integer", "null"]},
        "wait_for_seconds": {"type": ["integer", "null"]},
    },
    "required": ["verdict", "reason", "wait_on_session", "wait_on_pid", "wait_for_seconds"],
    "additionalProperties": False,
}

# Item types in `codex exec --json` events that mean the model acted rather than answered.
TOOL_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "collab_tool_call",
    "image_generation",
}
RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "429", "too many requests")
QUOTA_MARKERS = ("usage limit", "usage_limit", "quota")
TRANSIENT_MARKERS = ("timed out", "timeout", "connection", "502", "503", "504", "500")


class HarnessViolation(ArmHalted):
    """The CLI did something other than answer the prompt. Halts the arm for the run."""


class QuotaExhausted(ArmHalted):
    """The subscription's usage limit was hit; stop the arm and resume later."""


def render_prompt(messages: list[dict[str, str]]) -> str:
    """System message first, then the user message: static instructions before the item."""
    return "\n\n".join(m["content"] for m in messages)


def schema_valid(text: str) -> bool:
    """True when the reply is exactly one JSON object matching VERDICT_SCHEMA."""
    try:
        data = json.loads(text)
    except ValueError:
        return False
    if not isinstance(data, dict) or set(data) != set(VERDICT_SCHEMA["required"]):
        return False
    props = VERDICT_SCHEMA["properties"]
    if data["verdict"] not in props["verdict"]["enum"] or not isinstance(data["reason"], str):
        return False
    if not (data["wait_on_session"] is None or isinstance(data["wait_on_session"], str)):
        return False
    return all(
        data[k] is None or (isinstance(data[k], int) and not isinstance(data[k], bool))
        for k in ("wait_on_pid", "wait_for_seconds")
    )


def parse_events(stdout: str) -> dict:
    """Pull session id, usage, reported model, tool use and errors out of the JSONL events."""
    out: dict = {"thread_id": "", "model": "", "usage": {}, "tools": [], "errors": [], "text": ""}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type", "")
        if kind == "thread.started":
            out["thread_id"] = str(ev.get("thread_id") or "")
        elif kind == "turn.completed":
            out["usage"] = ev.get("usage") or {}
        elif kind in ("error", "turn.failed"):
            err = ev.get("error") if isinstance(ev.get("error"), dict) else ev
            out["errors"].append(str(err.get("message") or err))
        item = ev.get("item") if isinstance(ev.get("item"), dict) else None
        if item:
            if item.get("type") in TOOL_ITEM_TYPES:
                out["tools"].append(item["type"])
            if item.get("type") == "agent_message" and kind == "item.completed":
                out["text"] = str(item.get("text") or "")
        for key in ("model", "model_slug"):
            if isinstance(ev.get(key), str) and ev[key]:
                out["model"] = ev[key]
    return out


def _classify(message: str) -> tuple[str, bool]:
    low = message.lower()
    if any(m in low for m in QUOTA_MARKERS):
        return "usage_limit", False
    if any(m in low for m in RATE_LIMIT_MARKERS):
        return "rate_limited", True
    if any(m in low for m in TRANSIENT_MARKERS):
        return "transient", True
    return "cli_error", False


def installed_version(executable: str) -> str:
    out = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True)
    return out.stdout.strip().removeprefix("codex-cli").strip()


class CodexClient:
    def __init__(
        self,
        arm: Arm,
        *,
        version: str,
        limiter: TokenBucket,
        executable: str | None = None,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = MAX_ATTEMPTS,
        check_version: bool = True,
    ):
        if arm.reasoning in ("", "provider-default"):
            raise ValueError("the Codex arm must pin a reasoning effort")
        self.arm = arm
        self.version = version
        self.limiter = limiter
        self.max_attempts = max_attempts
        self._run = run
        self._sleep = sleep
        self._exe = executable or shutil.which("codex") or "codex"
        if check_version:
            found = installed_version(self._exe)
            if found != version:
                raise RuntimeError(f"codex-cli {found} is installed; arm pinned to {version}")
        self._home = os.environ.get(CODEX_HOME_ENV, "")
        self._halted: ArmHalted | None = None
        self._schema_dir = Path(tempfile.mkdtemp(prefix="hjr-codex-schema-"))
        self._schema = self._schema_dir / "verdict.schema.json"
        self._schema.write_text(json.dumps(VERDICT_SCHEMA), encoding="utf-8")

    def command(self, cwd: Path, out_file: Path) -> list[str]:
        cmd = [
            self._exe,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--cd",
            str(cwd),
            "--model",
            self.arm.model_id,
            "-c",
            f'model_reasoning_effort="{self.arm.reasoning}"',
            "-c",
            'web_search="disabled"',
            "--output-schema",
            str(self._schema),
            "--output-last-message",
            str(out_file),
            "--color",
            "never",
        ]
        for feature in DISABLED_FEATURES:
            cmd += ["--disable", feature]
        return cmd + ["-"]

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._home:
            env["CODEX_HOME"] = self._home
        return env

    def complete(self, messages: list[dict[str, str]]) -> CompletionResult:
        if self._halted is not None:
            raise self._halted
        prompt = render_prompt(messages)
        log: list[Attempt] = []
        for n in range(1, self.max_attempts + 1):
            self.limiter.acquire()
            cwd = Path(tempfile.mkdtemp(prefix="hjr-codex-cwd-"))
            out_dir = Path(tempfile.mkdtemp(prefix="hjr-codex-out-"))
            out_file = out_dir / "last_message.txt"
            start = time.monotonic()
            try:
                proc = self._run(
                    self.command(cwd, out_file),
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=CALL_TIMEOUT_S,
                    env=self._env(),
                )
            except subprocess.TimeoutExpired:
                proc = None
            ms = int((time.monotonic() - start) * 1000)
            try:
                leftovers = sorted(p.name for p in cwd.iterdir())
                text = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
            finally:
                shutil.rmtree(cwd, ignore_errors=True)
                shutil.rmtree(out_dir, ignore_errors=True)
            if proc is None:
                log.append(Attempt(n, False, "timeout", None, True, ms))
                error, retryable = "timeout", True
            else:
                events = parse_events(proc.stdout or "")
                if events["tools"] or leftovers:
                    self._halted = HarnessViolation(
                        f"{self.arm.key}: call used tools {events['tools']} or wrote {leftovers}"
                    )
                    raise self._halted
                if proc.returncode == 0:
                    log.append(Attempt(n, True, latency_ms=ms))
                    return self._result(text or events["text"], events, ms, tuple(log))
                message = " | ".join(events["errors"]) or (proc.stderr or "")[-500:]
                error, retryable = _classify(message)
                log.append(Attempt(n, False, error, None, retryable, ms))
                if error == "usage_limit":
                    self._halted = QuotaExhausted(f"{self.arm.key}: {message[:200]}")
                    raise self._halted
            if not retryable or n == self.max_attempts:
                raise TransportError(f"codex exec failed: {error}", tuple(log))
            self._sleep(min(MAX_BACKOFF_S, BASE_BACKOFF_S * 2 ** (n - 1)))
        raise AssertionError("unreachable")

    def _result(
        self, text: str, events: dict, latency_ms: int, attempts: tuple[Attempt, ...]
    ) -> CompletionResult:
        usage = events["usage"]
        return CompletionResult(
            text=text.strip(),
            model_reported=events["model"],
            provider_reported=f"codex-cli {self.version}",
            finish_reason="completed",
            latency_ms=latency_ms,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            reasoning_tokens=int(usage.get("reasoning_output_tokens") or 0),
            cached_tokens=int(usage.get("cached_input_tokens") or 0),
            cost_usd=None,
            attempts=attempts,
            meta={
                "thread_id": events["thread_id"],
                "codex_version": self.version,
                "codex_home": "dedicated" if self._home else "default",
                "schema_valid": str(schema_valid(text.strip())).lower(),
            },
        )
