"""Load judge model definitions and seeds from ``configs/``."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"
JUDGE_CONFIG = CONFIGS / "judge_variants.toml"
SEEDS_CONFIG = CONFIGS / "seeds.toml"


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    api_key_env: str


@dataclass(frozen=True)
class JudgeModel:
    key: str
    id: str
    endpoint: Endpoint
    provider: str | None = None

    def describe(self) -> dict[str, str]:
        return {"id": self.id, "base_url": self.endpoint.base_url, "provider": self.provider or ""}


@dataclass(frozen=True)
class JudgeConfig:
    models: dict[str, JudgeModel]
    sha256: str

    def model(self, key: str) -> JudgeModel:
        try:
            return self.models[key]
        except KeyError:
            known = ", ".join(sorted(self.models))
            raise KeyError(f"unknown judge model {key!r} (known: {known})") from None


def load_judge_config(path: Path = JUDGE_CONFIG) -> JudgeConfig:
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    endpoints = {k: Endpoint(**v) for k, v in data.get("endpoints", {}).items()}
    models = {
        key: JudgeModel(
            key=key,
            id=spec["id"],
            endpoint=endpoints[spec["endpoint"]],
            provider=spec.get("provider"),
        )
        for key, spec in data.get("models", {}).items()
    }
    return JudgeConfig(models=models, sha256=hashlib.sha256(raw).hexdigest())


def global_seed(path: Path = SEEDS_CONFIG) -> int:
    return int(tomllib.loads(path.read_text(encoding="utf-8"))["global"])
