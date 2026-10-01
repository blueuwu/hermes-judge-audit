"""Harbor agent that runs Hermes under the /goal loop and records every turn boundary.

Extends Harbor's built-in ``Hermes`` agent with three changes:

1. ``install`` only checks the Hermes commit baked into ``hjr/hermes-base`` instead of running
   the upstream installer, which tracks ``main``.
2. ``run`` drives the goal loop (``hjr.goalloop``): one ``hermes chat --resume`` per turn, a
   workspace snapshot at every boundary, then the production judge.
3. The judge runs here, on the host, with the replay client; its key never enters the sandbox.

Per trial, the agent log dir gets ``turns.jsonl`` (one TurnRecord per boundary),
``judge_attempts.jsonl``, ``goal_loop.json`` and the raw Hermes output of every turn. Snapshots
go to ``/logs/artifacts/boundaries/bNN.tgz`` for the verifier.

A task with a ``stages/`` directory gets ``stages/stage_N`` copied to ``/app/evidence/stage_N``
just before turn N, so its evidence cannot be read early. In soak mode Hermes also dumps every
request body before sending it (``HERMES_DUMP_REQUESTS``); the dumps land in
``request_dumps/`` for the soak report's ``reasoning_content`` check.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from harbor.agents.installed.hermes import Hermes, HermesOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from pydantic import Field

from hjr import goalloop
from hjr.client import JudgeClient, TransportError
from hjr.config import JudgeConfig, load_judge_config
from hjr.judge import Variant
from hjr.manifest import hermes_sha
from hjr.ratelimit import Limiters
from hjr.replay import judge_once
from hjr.schemas import AttemptRecord, TurnRecord

HERMES_HOME = "/tmp/hermes"
WORKSPACE = "/app"
SNAPSHOT_DIR = "/logs/artifacts/boundaries"
AGENT_LOG_DIR = "/logs/agent"
PROMPT_DIR = "/tmp/hjr"
EVIDENCE_DIR = f"{WORKSPACE}/evidence"
# Even a soak stops here: the judge is unreachable or the turn budget is spent.
SOAK_STOPS = ("pause_transport", "budget")
PROCESS_FILTER = ("ps -eo args", "sleep infinity", "/bin/sh -c", "bash -c")
HERMES_PYTHON = "/opt/hermes/.venv/bin/python"
# Size of the turn's last request by Hermes's own estimate: system prompt, the hermes-cli tool
# schemas, and the history before the final reply (failed-turn notices included: Hermes sends
# them back), with reasoning_content where Hermes replays it (needs_reasoning_echo). Within ~10% of
# provider-reported prompt tokens on Qwen (no prompt caching). Runs in the sandbox, where
# Hermes's dependencies are installed.
CONTEXT_SCRIPT = """
import json, sys
from agent.message_sanitization import needs_reasoning_echo
from agent.model_metadata import estimate_request_tokens_rough
from model_tools import get_tool_definitions
s = json.loads(open(sys.argv[1], encoding="utf-8").readline())
sent = list(s["messages"])
if sent and sent[-1].get("role") == "assistant":
    sent = sent[:-1]
keys = ("role", "content", "tool_calls", "tool_call_id")
if needs_reasoning_echo("openrouter", sys.argv[2], "https://openrouter.ai/api/v1"):
    keys += ("reasoning_content",)
wire = [{k: m[k] for k in keys if m.get(k)} for m in sent]
tools = get_tool_definitions(enabled_toolsets=["hermes-cli"], quiet_mode=True)
print(estimate_request_tokens_rough(wire, system_prompt=s.get("system_prompt") or "", tools=tools))
"""

# One limiter set per Harbor process, shared by every concurrent trial.
_LIMITERS: Limiters | None = None
_LIMITERS_LOCK = threading.Lock()


def _limiters(cfg: JudgeConfig) -> Limiters:
    global _LIMITERS
    with _LIMITERS_LOCK:
        if _LIMITERS is None:
            _LIMITERS = Limiters(cfg.limits())
        return _LIMITERS


class GoalLoopOptions(HermesOptions):
    arm: str = Field(description="Agent arm in configs/judge_variants.toml ([agents.<arm>]).")
    max_turns: int = Field(default=6, ge=1, description="Goal turn budget for one trial.")
    turn_timeout_sec: int = Field(default=600, ge=30, description="Wall clock per Hermes turn.")
    soak: bool = Field(
        default=False,
        description=(
            "Compatibility soak: keep resuming past a production stop (DONE, BLOCKED, empty "
            "response) until max_turns, so long resumed sessions are exercised. Turns after "
            "the stop are marked past_stop and never enter analysis."
        ),
    )


class HermesGoalLoop(Hermes):
    options_model = GoalLoopOptions
    options: GoalLoopOptions

    def __init__(self, logs_dir: Path, *args: Any, **kwargs: Any):
        super().__init__(logs_dir, *args, **kwargs)
        self._cfg = load_judge_config()
        if self.options.arm not in self._cfg.agents:
            raise ValueError(f"unknown agent arm {self.options.arm!r}")
        agent = self._cfg.agents[self.options.arm]
        self._agent_model = agent["id"]
        self._agent_provider = agent["provider"]
        expected = f"openrouter/{self._agent_model}"
        if self.model_name and self.model_name != expected:
            raise ValueError(f"arm {self.options.arm!r} runs {expected}, not {self.model_name}")
        self.model_name = expected
        self._judge_key = f"self-{self.options.arm}"
        self._variant = Variant("prod-plain", self._judge_key, "head4k")

    @staticmethod
    def name() -> str:
        return "hermes-goal-loop"

    def get_version_command(self) -> str | None:
        return "cat /opt/hermes/HERMES_SHA"

    async def install(self, environment: BaseEnvironment) -> None:
        result = await environment.exec(command="cat /opt/hermes/HERMES_SHA")
        found = (result.stdout or "").strip()
        if found != hermes_sha():
            raise RuntimeError(f"sandbox Hermes is {found or 'missing'}, expected {hermes_sha()}")
        self._version = found

    # ── Hermes configuration ─────────────────────────────────────────

    def _config_yaml(self) -> str:
        """Harbor's Hermes config, routed through OpenRouter to the arm's one provider."""
        config = yaml.safe_load(self._build_config_yaml(self._agent_model))
        config["provider"] = "openrouter"
        config["provider_routing"] = {"only": [self._agent_provider]}
        return yaml.safe_dump(config, sort_keys=False)

    def _env(self) -> dict[str, str]:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        env = {"HERMES_HOME": HERMES_HOME, "TERMINAL_ENV": "local", "OPENROUTER_API_KEY": key}
        if self.options.soak:
            env["HERMES_DUMP_REQUESTS"] = "1"
        return env

    async def _upload_text(self, environment: BaseEnvironment, text: str, remote: str) -> None:
        with tempfile.TemporaryDirectory(prefix="hjr-") as tmp:
            local = Path(tmp) / Path(remote).name
            local.write_bytes(text.encode("utf-8"))
            await environment.upload_file(local, remote)

    # ── One turn ─────────────────────────────────────────────────────

    async def _hermes_turn(
        self, environment: BaseEnvironment, turn: int, prompt: str, session_id: str | None
    ) -> tuple[int | None, float]:
        prompt_path = f"{PROMPT_DIR}/prompt_{turn:02d}.txt"
        await self._upload_text(environment, prompt, prompt_path)
        parts = [
            "hermes --yolo chat",
            f"--query-file {prompt_path}",
            "-Q --source cli",
            f"--model {shlex.quote(self._agent_model)}",
            "--provider openrouter",
        ]
        if session_id:
            parts.append(f"--resume {shlex.quote(session_id)}")
        if self.options.toolsets:
            parts.append(f"--toolsets {shlex.quote(self.options.toolsets)}")
        cmd = f"cd {WORKSPACE} && {' '.join(parts)} > {AGENT_LOG_DIR}/turn_{turn:02d}.txt 2>&1"
        start = time.monotonic()
        try:
            result = await environment.exec(
                command=cmd, env=self._env(), timeout_sec=self.options.turn_timeout_sec
            )
            code = result.return_code
        except TimeoutError:
            code = None
        return code, time.monotonic() - start

    async def _export_session(
        self, environment: BaseEnvironment, turn: int, session_id: str | None
    ) -> tuple[str | None, list[dict[str, Any]]]:
        out = f"{AGENT_LOG_DIR}/session_{turn:02d}.jsonl"
        select = f"--session-id {shlex.quote(session_id)}" if session_id else "--source cli"
        result = await environment.exec(
            command=f"hermes sessions export {out} {select} >/dev/null 2>&1; cat {out}",
            env={"HERMES_HOME": HERMES_HOME},
            timeout_sec=60,
        )
        return goalloop.parse_session_export(result.stdout or "")

    async def _context_tokens(self, environment: BaseEnvironment, turn: int) -> int:
        export = f"{AGENT_LOG_DIR}/session_{turn:02d}.jsonl"
        result = await environment.exec(
            command=f"cd /opt/hermes && {HERMES_PYTHON} -c {shlex.quote(CONTEXT_SCRIPT)} "
            f"{export} {shlex.quote(self._agent_model)}",
            env={"HERMES_HOME": HERMES_HOME},
            timeout_sec=60,
        )
        try:
            return int((result.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 0

    async def _snapshot(self, environment: BaseEnvironment, turn: int) -> str:
        name = f"b{turn:02d}.tgz"
        await environment.exec(
            command=f"mkdir -p {SNAPSHOT_DIR} && tar czf {SNAPSHOT_DIR}/{name} -C {WORKSPACE} .",
            timeout_sec=60,
        )
        return name

    async def _processes(self, environment: BaseEnvironment) -> list[str]:
        result = await environment.exec(command="ps -eo args --no-headers", timeout_sec=10)
        lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
        return [ln for ln in lines if not any(f in ln for f in PROCESS_FILTER)]

    def _task_dir(self) -> Path | None:
        """The task directory, from the trial config Harbor writes before the agent runs."""
        config = self.logs_dir.parent / "config.json"
        try:
            return Path(json.loads(config.read_text(encoding="utf-8"))["task"]["path"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def _release_stage(
        self, environment: BaseEnvironment, task_dir: Path | None, turn: int
    ) -> str | None:
        stage = task_dir / "stages" / f"stage_{turn}" if task_dir else None
        if stage is None or not stage.is_dir():
            return None
        await environment.upload_dir(stage, f"{EVIDENCE_DIR}/stage_{turn}")
        return stage.name

    def _judge(self, pending: TurnRecord, client: JudgeClient):
        return judge_once(
            pending, self._variant, 0, self._cfg.model(self._judge_key), client.complete
        )

    # ── The loop ─────────────────────────────────────────────────────

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        goal = instruction
        trial = self.logs_dir.parent.name
        run_id = self.logs_dir.parent.parent.name
        task = trial.split("__")[0]
        judge_arm = self._cfg.model(self._judge_key)
        client = JudgeClient(
            judge_arm,
            api_key_env=self._cfg.endpoint(judge_arm).api_key_env,
            limiter=_limiters(self._cfg).get(self._cfg.limiter_key(self._judge_key)),
        )
        await environment.exec(
            command=f"mkdir -p {HERMES_HOME} {PROMPT_DIR} {AGENT_LOG_DIR} {SNAPSHOT_DIR}"
        )
        await self._upload_text(environment, self._config_yaml(), f"{HERMES_HOME}/config.yaml")

        task_dir = self._task_dir()
        state = goalloop.LoopState(max_turns=self.options.max_turns)
        session_id: str | None = None
        seen = 0
        stopped = False  # production would have ended the goal before this turn
        summary: dict[str, Any] = {
            "arm": self.options.arm,
            "agent_model": self._agent_model,
            "agent_provider": self._agent_provider,
            "judge": str(self._variant),
            "judge_arm_id": judge_arm.arm_id,
            "max_turns": self.options.max_turns,
            "soak": self.options.soak,
            "turns": 0,
            "end": None,
            "production_end": None,
            "released": [],
        }
        try:
            for turn in range(1, self.options.max_turns + 1):
                released = await self._release_stage(environment, task_dir, turn)
                if released:
                    summary["released"].append({"turn": turn, "stage": released})
                prompt = goalloop.turn_prompt(goal, turn)
                code, seconds = await self._hermes_turn(environment, turn, prompt, session_id)
                session_id, messages = await self._export_session(environment, turn, session_id)
                snapshot = await self._snapshot(environment, turn)
                last = goalloop.last_assistant_text(messages)
                pending = TurnRecord(
                    boundary_id=f"{run_id}/{trial}/b{turn:02d}",
                    run_id=run_id,
                    trial=trial,
                    task_id=f"hjr/{task}",
                    agent_arm=self.options.arm,
                    agent_model=self._agent_model,
                    turn=turn,
                    prompt=prompt,
                    goal=goal,
                    last_response=last,
                    last_response_kind=goalloop.last_assistant_kind(messages),
                    response_chars=len(last),
                    context_tokens_est=await self._context_tokens(environment, turn),
                    session_id=session_id,
                    recent_tool_events=goalloop.tool_events(messages[seen:]),
                    tool_calls_total=goalloop.count_tool_calls(messages),
                    processes_running=await self._processes(environment),
                    snapshot=snapshot,
                    agent_exit_code=code,
                    agent_seconds=round(seconds, 1),
                    past_stop=stopped,
                    ts=datetime.now(UTC),
                )
                seen = len(messages)
                verdict, error = None, ""
                try:
                    verdict, attempts = await asyncio.to_thread(self._judge, pending, client)
                except TransportError as exc:
                    error, attempts = str(exc), exc.attempts
                self._log_attempts(pending, attempts, judge_arm.arm_id)
                action = state.after_turn(
                    last,
                    verdict=verdict.verdict if verdict and verdict.outcome != "no_call" else None,
                    parse_failed=bool(verdict and verdict.parse_failed),
                    transport_failed=bool(error),
                )
                record = pending.model_copy(
                    update={"controller": verdict, "controller_error": error, "action": action}
                )
                self._append("turns.jsonl", record.model_dump_json())
                summary.update(turns=turn, end=action, session_id=session_id)
                if action != "continue" and not stopped:
                    summary["production_end"] = {"turn": turn, "action": action}
                    stopped = True
                if action == "continue" or (self.options.soak and action not in SOAK_STOPS):
                    continue
                break
        finally:
            (self.logs_dir / "goal_loop.json").write_text(json.dumps(summary, indent=2) + "\n")
            await environment.exec(
                command=f"cp $(ls {AGENT_LOG_DIR}/session_*.jsonl | tail -1) "
                f"{AGENT_LOG_DIR}/hermes-session.jsonl 2>/dev/null || true; "
                f"cp -r {HERMES_HOME}/logs {AGENT_LOG_DIR}/hermes-logs 2>/dev/null || true; "
                f"mkdir -p {AGENT_LOG_DIR}/request_dumps && "
                f"cp {HERMES_HOME}/sessions/request_dump_*.json {AGENT_LOG_DIR}/request_dumps/ "
                "2>/dev/null || true"
            )

    def _append(self, name: str, line: str) -> None:
        with (self.logs_dir / name).open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")

    def _log_attempts(self, pending: TurnRecord, attempts, arm_id: str) -> None:
        for a in attempts:
            rec = AttemptRecord(
                boundary_id=pending.boundary_id,
                variant=str(self._variant),
                sample=0,
                arm_id=arm_id,
                attempt=a.attempt,
                status="ok" if a.ok else "error",
                error_type=a.error_type,
                http_status=a.http_status,
                retryable=a.retryable,
                latency_ms=a.latency_ms,
                ts=datetime.now(UTC),
            )
            self._append("judge_attempts.jsonl", rec.model_dump_json(exclude_none=True))
