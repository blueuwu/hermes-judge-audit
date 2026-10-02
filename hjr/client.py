"""OpenAI-compatible judge client: provider pinning, rate limiting, logged retries.

A call either returns a CompletionResult (the model answered, whatever it said) or raises
TransportError. Transport failures are never turned into verdicts.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import openai

from hjr.arms import Arm
from hjr.ratelimit import TokenBucket

REQUEST_TIMEOUT_S = 120.0
MAX_ATTEMPTS = 6
MAX_BACKOFF_S = 120.0

RETRYABLE_ERRORS = (openai.APIConnectionError, openai.APITimeoutError)
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
# Production sends no reasoning configuration; any other value is sent as an effort level.
REASONING_DEFAULT = "provider-default"


@dataclass(frozen=True)
class Attempt:
    attempt: int
    ok: bool
    error_type: str = ""
    http_status: int | None = None
    retryable: bool = False
    latency_ms: int = 0


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model_reported: str = ""
    provider_reported: str = ""
    finish_reason: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float | None = None
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)
    # Serving metadata that has no field of its own (CLI session id, harness version)
    meta: dict[str, str] = field(default_factory=dict)


class TransportError(RuntimeError):
    def __init__(self, message: str, attempts: tuple[Attempt, ...]):
        super().__init__(message)
        self.attempts = attempts


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _extra(obj, name: str):
    extra = getattr(obj, "model_extra", None) or {}
    return extra.get(name)


class JudgeClient:
    def __init__(
        self,
        arm: Arm,
        *,
        api_key_env: str,
        limiter: TokenBucket,
        timeout: float = REQUEST_TIMEOUT_S,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        client: openai.OpenAI | None = None,
    ):
        self.arm = arm
        self.limiter = limiter
        self.max_attempts = max_attempts
        self._sleep = sleep
        if client is None:
            key = os.environ.get(api_key_env)
            if not key:
                raise RuntimeError(f"{api_key_env} is not set")
            client = openai.OpenAI(
                base_url=arm.base_url, api_key=key, timeout=timeout, max_retries=0
            )
        self._client = client

    def _extra_body(self) -> dict | None:
        body: dict = {}
        if self.arm.provider:
            body["provider"] = {"order": [self.arm.provider], "allow_fallbacks": False}
        if "openrouter.ai" in self.arm.base_url:
            body["usage"] = {"include": True}  # per-request cost in the response
        if self.arm.reasoning != REASONING_DEFAULT:
            body["reasoning"] = {"effort": self.arm.reasoning}
        return body or None

    def _request(self, messages: list[dict[str, str]]):
        # Parameters the arm leaves unset are not sent at all, rather than sent and dropped.
        params: dict = {}
        if self.arm.temperature is not None:
            params["temperature"] = self.arm.temperature
        if self.arm.max_tokens is not None:
            params["max_tokens"] = self.arm.max_tokens
        return self._client.chat.completions.create(
            model=self.arm.model_id,
            messages=messages,
            extra_body=self._extra_body(),
            **params,
        )

    def complete(self, messages: list[dict[str, str]]) -> CompletionResult:
        log: list[Attempt] = []
        for n in range(1, self.max_attempts + 1):
            self.limiter.acquire()
            start = time.monotonic()
            try:
                resp = self._request(messages)
            except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
                ms = int((time.monotonic() - start) * 1000)
                status = _status(exc)
                retryable = isinstance(exc, RETRYABLE_ERRORS) or status in RETRYABLE_STATUS
                log.append(Attempt(n, False, type(exc).__name__, status, retryable, ms))
                if not retryable or n == self.max_attempts:
                    raise TransportError(f"{type(exc).__name__}: {exc}", tuple(log)) from exc
                backoff = _retry_after(exc) or min(MAX_BACKOFF_S, 2.0**n)
                self._sleep(backoff + random.uniform(0, 1))
                continue
            ms = int((time.monotonic() - start) * 1000)
            log.append(Attempt(n, True, latency_ms=ms))
            return self._result(resp, ms, tuple(log))
        raise AssertionError("unreachable")

    def _result(self, resp, latency_ms: int, attempts: tuple[Attempt, ...]) -> CompletionResult:
        choice = resp.choices[0] if resp.choices else None
        usage = resp.usage
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        cost = _extra(usage, "cost") if usage else None
        return CompletionResult(
            text=(choice.message.content if choice else None) or "",
            model_reported=resp.model or "",
            provider_reported=str(_extra(resp, "provider") or ""),
            finish_reason=(choice.finish_reason if choice else "") or "",
            latency_ms=latency_ms,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            reasoning_tokens=(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
            cached_tokens=(getattr(prompt_details, "cached_tokens", 0) or 0)
            if prompt_details
            else 0,
            cost_usd=float(cost) if cost is not None else None,
            attempts=attempts,
        )
