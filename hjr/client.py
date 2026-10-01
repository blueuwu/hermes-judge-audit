"""OpenAI-compatible chat client for judge calls, with provider pinning and retries."""

from __future__ import annotations

import os
import time

import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from hjr.config import JudgeModel
from hjr.judge import MAX_TOKENS, TEMPERATURE, CompletionResult

RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)
REQUEST_TIMEOUT_S = 120.0


class JudgeClient:
    def __init__(self, model: JudgeModel, *, timeout: float = REQUEST_TIMEOUT_S):
        key = os.environ.get(model.endpoint.api_key_env)
        if not key:
            raise RuntimeError(f"{model.endpoint.api_key_env} is not set")
        self.model = model
        self._client = openai.OpenAI(
            base_url=model.endpoint.base_url, api_key=key, timeout=timeout, max_retries=0
        )

    def _extra_body(self) -> dict | None:
        if not self.model.provider:
            return None
        return {"provider": {"order": [self.model.provider], "allow_fallbacks": False}}

    @retry(
        retry=retry_if_exception_type(RETRYABLE),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def complete(self, messages: list[dict[str, str]]) -> CompletionResult:
        start = time.monotonic()
        resp = self._client.chat.completions.create(
            model=self.model.id,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            extra_body=self._extra_body(),
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        usage = resp.usage
        text = resp.choices[0].message.content if resp.choices else None
        return CompletionResult(
            text=text or "",
            model_reported=resp.model or "",
            latency_ms=latency_ms,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
        )
