"""Load judge arms and seeds from ``configs/``."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hjr.arms import Arm

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"
JUDGE_CONFIG = CONFIGS / "judge_variants.toml"
SEEDS_CONFIG = CONFIGS / "seeds.toml"


@dataclass(frozen=True)
class Endpoint:
    name: str
    base_url: str
    api_key_env: str
    rpm: int
    dev_only: bool = False


@dataclass(frozen=True)
class JudgeConfig:
    endpoints: dict[str, Endpoint]
    agents: dict[str, dict[str, str]]
    models: dict[str, Arm]
    sampling: dict[str, object]
    sha256: str
    # Judge-side request limits per model key, for models whose provider caps them below their
    # endpoint's limit. Throttling does not change outputs, so it is not part of arm identity.
    model_rpm: dict[str, int] = field(default_factory=dict)

    def model(self, key: str) -> Arm:
        try:
            return self.models[key]
        except KeyError:
            known = ", ".join(sorted(self.models))
            raise KeyError(f"unknown judge model {key!r} (known: {known})") from None

    def endpoint(self, arm: Arm) -> Endpoint:
        return self.endpoints[arm.endpoint]

    def limits(self) -> dict[str, int]:
        """Requests per minute for every limiter: one per endpoint, one per capped model."""
        return {name: ep.rpm for name, ep in self.endpoints.items()} | {
            f"model:{key}": rpm for key, rpm in self.model_rpm.items()
        }

    def limiter_key(self, key: str) -> str:
        return f"model:{key}" if key in self.model_rpm else self.model(key).endpoint


def _arm(key: str, spec: dict, endpoints: dict[str, Endpoint], sampling: dict) -> Arm:
    ep = endpoints[spec["endpoint"]]
    return Arm(
        key=key,
        model_id=spec["id"],
        endpoint=ep.name,
        base_url=ep.base_url,
        provider=spec.get("provider", ""),
        temperature=float(sampling["temperature"]),
        max_tokens=int(sampling["max_tokens"]),
        reasoning=str(sampling["reasoning"]),
        dev_only=ep.dev_only,
        source=spec.get("source", ""),
        substitution=spec.get("substitution", ""),
    )


def load_judge_config(path: Path = JUDGE_CONFIG) -> JudgeConfig:
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    sampling = data["judge_sampling"]
    endpoints = {
        name: Endpoint(
            name=name,
            base_url=v["base_url"],
            api_key_env=v["api_key_env"],
            rpm=int(v["rpm"]),
            dev_only=bool(v.get("dev_only", False)),
        )
        for name, v in data.get("endpoints", {}).items()
    }
    # Agents record serving identity only; their sampling is whatever Hermes sends at run time.
    agents = dict(data.get("agents", {}))
    models = {}
    model_rpm = {k: int(v["rpm"]) for k, v in data.get("models", {}).items() if "rpm" in v}
    for key, spec in data.get("models", {}).items():
        if "self_of" in spec:
            # A self judge is the agent's model on the agent's provider, with judge sampling.
            agent = agents[spec["self_of"]]
            spec = {**agent, "source": spec.get("source", "")}
        models[key] = _arm(key, spec, endpoints, sampling)
    return JudgeConfig(
        endpoints, agents, models, dict(sampling), hashlib.sha256(raw).hexdigest(), model_rpm
    )


def global_seed(path: Path = SEEDS_CONFIG) -> int:
    return int(tomllib.loads(path.read_text(encoding="utf-8"))["global"])
