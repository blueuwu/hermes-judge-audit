from __future__ import annotations

import httpx

from hjr.config import load_judge_config
from hjr.routes import check_routes

CFG = load_judge_config()
# Routes on OpenRouter; the Codex CLI arm has no listing to check and is pinned by version.
N_PINNED = sum(not arm.dev_only and "openrouter.ai" in arm.base_url for arm in CFG.models.values())


def _client(served: dict[str, list[str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        model = request.url.path.split("/models/")[1].rsplit("/endpoints", 1)[0]
        if model not in served:
            return httpx.Response(404, json={"error": "not found"})
        endpoints = [
            {"tag": tag, "pricing": {"prompt": "0.0000005", "completion": "0.000003"}}
            for tag in served[model]
        ]
        return httpx.Response(200, json={"data": {"id": model, "endpoints": endpoints}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_all_pinned_routes_present():
    served = {
        "google/gemini-3-flash-preview": ["google-ai-studio", "google-ai-studio/flex"],
        "google/gemini-3.8-flash": ["google-ai-studio"],
        "z-ai/glm-5.3-flash": ["z-ai/fp8", "deepinfra/fp4"],
        "deepseek/deepseek-v4.1-flash": ["deepseek", "deepinfra/fp8"],
        "openai/gpt-6.1-sol": ["openai", "openai/flex", "azure"],
    }
    results = list(check_routes(CFG, client=_client(served)))
    assert len(results) == N_PINNED and all(ok for _, ok in results)


def test_retired_model_and_missing_provider_fail():
    served = {"google/gemini-3.8-flash": ["google-vertex/global"]}
    results = dict(check_routes(CFG, client=_client(served)))
    assert len(results) == N_PINNED and not any(results.values())
    assert any("not listed" in line for line in results)
    assert any("not served by google-ai-studio" in line for line in results)
