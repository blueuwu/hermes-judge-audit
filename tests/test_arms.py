from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from hermes_cli import goals as hg

from hjr import judge
from hjr.arms import Arm, MixedArmError, require_single_arm, sub_arm_id
from hjr.config import load_judge_config

CFG = load_judge_config()


def test_judge_sampling_matches_pinned_hermes():
    assert CFG.sampling["temperature"] == judge.TEMPERATURE == 0.0
    assert CFG.sampling["max_tokens"] == judge.MAX_TOKENS == hg.DEFAULT_JUDGE_MAX_TOKENS
    for arm in CFG.models.values():
        assert (arm.temperature, arm.max_tokens) == (judge.TEMPERATURE, judge.MAX_TOKENS)


def test_self_judge_uses_agent_model_and_provider():
    agent = CFG.agents["weak"]
    arm = CFG.model("self-weak")
    assert (arm.model_id, arm.provider) == (agent["id"], agent["provider"])
    assert arm.endpoint == agent["endpoint"]


def test_evaluation_arms_pin_a_provider_and_cite_a_source():
    for arm in CFG.models.values():
        assert arm.source, f"{arm.key} needs a source"
        if not arm.dev_only:
            assert arm.provider, f"{arm.key} must pin a provider"


def test_flash_and_drift_share_a_route():
    flash, drift = CFG.model("flash"), CFG.model("drift")
    assert flash.model_id == "google/gemini-3-flash-preview"
    assert (flash.base_url, flash.provider) == (drift.base_url, drift.provider)
    assert flash.arm_id != drift.arm_id


def test_dev_arm_is_flagged_and_distinct():
    dev = CFG.model("flash-dev")
    assert dev.dev_only and not CFG.model("flash").dev_only
    assert dev.arm_id != CFG.model("flash").arm_id


def test_arm_id_ignores_key_and_notes_but_tracks_behaviour():
    arm = CFG.model("flash")
    renamed = dataclasses.replace(arm, key="other", source="x", substitution="y")
    assert renamed.arm_id == arm.arm_id
    for change in ({"temperature": 0.7}, {"max_tokens": 1024}, {"provider": "google-vertex"}):
        assert dataclasses.replace(arm, **change).arm_id != arm.arm_id


def _rec(arm_id, sub):
    return SimpleNamespace(arm_id=arm_id, sub_arm_id=sub)


def test_require_single_arm():
    assert require_single_arm([_rec("a", "s"), _rec("a", "s")]) == ("a", "s")
    with pytest.raises(MixedArmError):
        require_single_arm([_rec("a", "s"), _rec("b", "s")])
    with pytest.raises(MixedArmError):
        require_single_arm([_rec("a", "s1"), _rec("a", "s2")])
    with pytest.raises(ValueError):
        require_single_arm([])


def test_sub_arm_id_tracks_reported_identity():
    base = sub_arm_id("a", "google/gemini-3-flash-preview", "Google AI Studio")
    assert base == sub_arm_id("a", "google/gemini-3-flash-preview", "Google AI Studio")
    assert base != sub_arm_id("a", "google/gemini-3-flash-preview-0915", "Google AI Studio")
    assert base != sub_arm_id("a", "google/gemini-3-flash-preview", "Google Vertex")


def test_arm_describe_has_identity_and_source():
    d = CFG.model("flash").describe()
    assert d["arm_id"] == CFG.model("flash").arm_id
    assert "goals.md:244" in d["source"]
    assert isinstance(Arm, type)


def test_agent_arms_differ_in_vendor_and_provider():
    weak, strong = CFG.model("self-weak"), CFG.model("self-strong")
    assert weak.model_id.split("/")[0] != strong.model_id.split("/")[0]
    assert weak.provider != strong.provider


def test_capped_model_gets_its_own_limiter():
    assert CFG.limiter_key("drift") == "model:drift"
    assert CFG.limiter_key("flash") == "openrouter"
    assert CFG.limits()["model:drift"] < CFG.endpoints["openrouter"].rpm
