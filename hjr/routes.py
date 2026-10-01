"""Check pinned OpenRouter routes from public model metadata. Makes no model calls."""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from hjr.config import JudgeConfig

ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"


def check_routes(
    cfg: JudgeConfig, keys: list[str] | None = None, *, client: httpx.Client | None = None
) -> Iterator[tuple[str, bool]]:
    client = client or httpx.Client(timeout=30)
    for key, arm in sorted(cfg.models.items()):
        if keys and key not in keys:
            continue
        if arm.dev_only or "openrouter.ai" not in arm.base_url:
            continue
        resp = client.get(ENDPOINTS_URL.format(model=arm.model_id))
        if resp.status_code != 200:
            yield f"{key}: {arm.model_id} not listed (HTTP {resp.status_code})", False
            continue
        endpoints = (resp.json().get("data") or {}).get("endpoints") or []
        match = [e for e in endpoints if (e.get("tag") or "").split("/")[0] == arm.provider]
        if not match:
            served = sorted({(e.get("tag") or "").split("/")[0] for e in endpoints})
            yield f"{key}: {arm.model_id} not served by {arm.provider} (served by {served})", False
            continue
        tags = ", ".join(
            f"{e.get('tag')} ${float(e['pricing']['prompt']) * 1e6:.3g}/"
            f"${float(e['pricing']['completion']) * 1e6:.3g} per 1M"
            for e in match
        )
        yield f"{key}: {arm.model_id} via {tags}", True
