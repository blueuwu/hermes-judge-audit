"""Arm identity: what exactly produced a record, and a guard against pooling different arms.

An arm is the serving identity plus decoding parameters. ``arm_id`` hashes only fields that
change model behaviour, so renaming a config key does not change it. A sub-arm adds the
identity the provider reports on each response; a mid-run change in that identity splits an
arm into sub-arms that are never pooled by default.

Only provider-reported identity is observable. A snapshot swapped behind an unchanged model id
and provider name cannot be detected from response metadata.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass


def _digest(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Arm:
    key: str
    model_id: str
    endpoint: str
    base_url: str
    provider: str
    temperature: float
    max_tokens: int
    reasoning: str
    dev_only: bool = False
    source: str = ""
    substitution: str = ""

    def identity(self) -> dict:
        return {
            "model_id": self.model_id,
            "base_url": self.base_url,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning": self.reasoning,
        }

    @property
    def arm_id(self) -> str:
        return _digest(self.identity())

    def describe(self) -> dict[str, str]:
        out = {k: str(v) for k, v in self.identity().items()}
        out.update(arm_id=self.arm_id, dev_only=str(self.dev_only).lower(), source=self.source)
        if self.substitution:
            out["substitution"] = self.substitution
        return out


def sub_arm_id(arm_id: str, model_reported: str, provider_reported: str) -> str:
    return _digest(
        {"arm_id": arm_id, "model_reported": model_reported, "provider_reported": provider_reported}
    )


class MixedArmError(ValueError):
    """Raised when records from different arms or sub-arms would be pooled."""


def require_single_arm(records: Iterable, *, what: str = "records") -> tuple[str, str]:
    """Return the shared (arm_id, sub_arm_id) of ``records``; raise if there is more than one."""
    seen = {(r.arm_id, r.sub_arm_id) for r in records}
    if len(seen) > 1:
        detail = ", ".join(f"{a}/{s}" for a, s in sorted(seen))
        raise MixedArmError(f"refusing to pool {what} from {len(seen)} arms: {detail}")
    if not seen:
        raise ValueError(f"no {what} to pool")
    return next(iter(seen))
