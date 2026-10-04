"""The mutation suite: verifier versions, frozen mutants, coverage and the kill rule."""

from __future__ import annotations

import io
import tarfile
import tomllib

import pytest

from hjr import mutants, verifier
from hjr.mutants import Mutant, outcome, run
from tests.taskutil import TASK_DIRS

TASKS = [p.name for p in TASK_DIRS if not p.name.startswith("s0-")]
REGISTRY = mutants.load_all()


def _requirements(task: str) -> list[str]:
    doc = tomllib.loads((verifier.TASKS / task / "task.toml").read_text(encoding="utf-8"))
    return doc["metadata"]["requirements"]


def _of(task: str, kind: str) -> list[Mutant]:
    return [m for m in REGISTRY.values() if m.task == task and m.kind == kind]


@pytest.mark.parametrize("task", TASKS)
def test_verifier_changes_need_a_version_bump(task):
    version, sha = verifier.version_of(task)
    assert verifier.tests_sha(task) == sha, f"{task}: tests/ changed; bump {version}"


def test_every_task_has_a_version_and_a_base():
    assert sorted(verifier.load_versions()) == TASKS
    assert sorted(run.load_bases()) == TASKS


def test_frozen_mutants_are_never_edited_or_deleted():
    assert mutants.drift(mutants.load_frozen(), mutants.current()) == []


def test_retired_mutants_still_exist():
    assert set(mutants.retired()) <= set(REGISTRY)


@pytest.mark.parametrize("task", TASKS)
def test_every_feasible_requirement_has_a_req_mutant(task):
    reqs, inf = _requirements(task), run.infeasible(task)
    covered = {m.breaks[0] for m in _of(task, "req")}
    assert covered == set(reqs) - set(inf)


@pytest.mark.parametrize("task", TASKS)
def test_lookalikes_and_declared_breaks(task):
    reqs, inf = set(_requirements(task)), run.infeasible(task)
    assert len(_of(task, "look")) >= 2
    for m in _of(task, "look") + _of(task, "con"):
        assert set(m.breaks) <= reqs
        if inf:  # truth is always blocked, so the kill rule needs named requirements
            assert m.breaks, m.key


def test_benign_variants_per_family_and_on_known_strict_tasks():
    families = {m.task[:2] for m in REGISTRY.values() if m.kind == "benign"}
    assert families == {"c1", "c2", "c3", "c4", "c5", "c6"}
    strict = [m for m in REGISTRY.values() if m.kind == "benign" and m.task in STRICT]
    assert len(strict) >= 2


STRICT = ("c2-01-rename-function", "c6-04-data-quality-report")


def _m(kind_id: str, breaks=()) -> Mutant:
    return Mutant("t", kind_id, "", lambda ws: None, breaks)


K, C, S = "killed_targeted", "killed_collateral", "survived_verdict"


@pytest.mark.parametrize(
    "mutant, truth, failing, inf, want",
    [
        (_m("req:a", ("a",)), "not_done", {"a"}, (), (K, [])),
        (_m("req:a", ("a",)), "not_done", {"a", "b"}, (), (K, ["b"])),
        (_m("req:a", ("a",)), "not_done", {"b"}, (), (C, ["b"])),
        (_m("req:a", ("a",)), "done", set(), (), (S, [])),
        (_m("look:x", ("a",)), "not_done", {"b"}, (), (C, ["b"])),
        (_m("look:x", ("a", "b")), "not_done", {"a"}, (), (C, [])),
        (_m("look:x", ("a", "b")), "not_done", {"a", "b"}, (), (K, [])),
        (_m("look:x"), "not_done", {"b"}, (), (C, ["b"])),  # no targets: never targeted
        (_m("look:x", ("a",)), "done", set(), (), (S, [])),
        (_m("look:x", ("up",)), "blocked", {"up"}, ("up",), (K, [])),
        (_m("look:x", ("up", "a")), "blocked", {"up"}, ("up",), (S, [])),
        (_m("req:a", ("a",)), "blocked", {"a", "up"}, ("up",), (K, [])),
        (_m("benign:x"), "done", set(), (), ("accepted", [])),
        (_m("benign:x"), "not_done", {"a"}, (), ("rejected", [])),
        (_m("benign:x"), "blocked", {"up"}, ("up",), ("accepted", [])),
        (_m("benign:x"), "blocked", {"up", "a"}, ("up",), ("rejected", [])),
    ],
)
def test_kill_rule(mutant, truth, failing, inf, want):
    reqs = {k: k not in failing for k in ("a", "b", "up")}
    assert outcome(mutant, truth, reqs, inf) == want


def test_broken_means_no_targeted_check_failed():
    m = _m("look:x", ("a", "b"))
    assert mutants.broken(m, {"a": True, "b": True, "up": False})
    assert not mutants.broken(m, {"a": False, "b": True})


def test_every_mutant_has_targets():
    for m in REGISTRY.values():
        assert bool(m.targets) == (m.kind != "benign"), m.key
    assert set(mutants.load_targets()) <= set(REGISTRY)


def test_snapshots_are_packed_like_the_harness(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f.txt").write_text("x")
    with tarfile.open(fileobj=io.BytesIO(verifier.snapshot_tgz(tmp_path)), mode="r:gz") as tf:
        names = sorted(tf.getnames())
        assert names == [".", "./d", "./d/f.txt"]
        assert {m.uid for m in tf.getmembers()} == {0}


def test_infeasible_is_read_without_importing():
    assert run.infeasible("c5-01-upload-without-credentials") == ("uploaded",)
    assert run.infeasible("c1-01-csv-to-json") == ()
