"""JudgeClient against a stub OpenAI client: retries, classification, metadata. No network."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

from hjr.client import JudgeClient, TransportError
from hjr.config import load_judge_config
from hjr.ratelimit import TokenBucket

ARM = load_judge_config().model("flash")


def _status_error(cls, status, retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status, headers=headers, request=request)
    return cls("err", response=response, body=None)


def _response(content='{"verdict": "done", "reason": "ok"}', finish="stop"):
    usage = SimpleNamespace(
        prompt_tokens=1200,
        completion_tokens=40,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=25),
        model_extra={"cost": 0.00071},
    )
    choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model="google/gemini-3-flash-preview",
        model_extra={"provider": "Google AI Studio"},
    )


class StubOpenAI:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _client(outcomes, max_attempts=4):
    stub = StubOpenAI(outcomes)
    sleeps = []
    client = JudgeClient(
        ARM,
        api_key_env="UNUSED",
        limiter=TokenBucket(6000, burst=100),
        max_attempts=max_attempts,
        sleep=sleeps.append,
        client=stub,
    )
    return client, stub, sleeps


def test_success_records_serving_metadata():
    client, stub, _ = _client([_response()])
    res = client.complete([{"role": "user", "content": "x"}])
    assert res.model_reported == "google/gemini-3-flash-preview"
    assert res.provider_reported == "Google AI Studio"
    assert (res.finish_reason, res.reasoning_tokens, res.cost_usd) == ("stop", 25, 0.00071)
    assert len(res.attempts) == 1 and res.attempts[0].ok
    req = stub.requests[0]
    assert req["temperature"] == 0.0 and req["max_tokens"] == 4096
    assert req["extra_body"]["provider"] == {
        "order": ["google-ai-studio"],
        "allow_fallbacks": False,
    }
    assert req["extra_body"]["usage"] == {"include": True}


def test_retries_429_then_succeeds_and_honours_retry_after():
    client, _, sleeps = _client([_status_error(openai.RateLimitError, 429, 7), _response()])
    res = client.complete([])
    assert [a.ok for a in res.attempts] == [False, True]
    assert res.attempts[0].http_status == 429 and res.attempts[0].retryable
    assert 7 <= sleeps[0] < 8


def test_gives_up_after_max_attempts():
    errors = [openai.APITimeoutError(request=httpx.Request("POST", "http://x"))] * 3
    client, _, _ = _client(errors, max_attempts=3)
    with pytest.raises(TransportError) as info:
        client.complete([])
    assert len(info.value.attempts) == 3
    assert all(not a.ok and a.retryable for a in info.value.attempts)


def test_non_retryable_status_fails_immediately():
    client, stub, _ = _client([_status_error(openai.AuthenticationError, 401), _response()])
    with pytest.raises(TransportError) as info:
        client.complete([])
    assert len(stub.requests) == 1
    assert info.value.attempts[0].http_status == 401 and not info.value.attempts[0].retryable


def test_empty_content_is_a_response_not_a_transport_error():
    client, _, _ = _client([_response(content=None, finish="length")])
    res = client.complete([])
    assert (res.text, res.finish_reason) == ("", "length")


def test_unset_sampling_is_not_sent_and_pinned_effort_is():
    stub = StubOpenAI([_response()])
    client = JudgeClient(
        load_judge_config().model("strong-api"),
        api_key_env="UNUSED",
        limiter=TokenBucket(6000, burst=100),
        client=stub,
    )
    client.complete([])
    req = stub.requests[0]
    assert "temperature" not in req and "max_tokens" not in req
    assert req["extra_body"]["reasoning"] == {"effort": "medium"}
    assert req["extra_body"]["provider"]["order"] == ["openai"]


def test_production_arms_send_no_reasoning_config():
    client, stub, _ = _client([_response()])
    client.complete([])
    assert "reasoning" not in stub.requests[0]["extra_body"]


def test_cached_prompt_tokens_are_recorded():
    resp = _response()
    resp.usage.prompt_tokens_details = SimpleNamespace(cached_tokens=640)
    client, _, _ = _client([resp])
    assert client.complete([]).cached_tokens == 640
