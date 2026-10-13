from __future__ import annotations

import io
import tarfile

from hjr import state_replay, verifier
from hjr.schemas import ToolEvent


def _tgz(files: dict[str, tuple[bytes, int]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(f"./{name}")
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_pack_restores_snapshot_modes_lost_on_extraction(tmp_path):
    tgz = _tgz({"bin/run.sh": (b"#!/bin/sh\n", 0o755), "data.txt": (b"x", 0o644)})
    modes = state_replay.snapshot_modes(tgz)
    assert modes["bin/run.sh"] == 0o755
    state_replay.extract(tgz, tmp_path / "ws")
    packed = state_replay.pack(tmp_path / "ws", modes)
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as tf:
        got = {m.name.removeprefix("./"): m.mode for m in tf.getmembers() if m.isfile()}
    assert got == {"bin/run.sh": 0o755, "data.txt": 0o644}


def test_identical_trees_are_graded_once(tmp_path, monkeypatch):
    calls = []

    def fake(task, snaps, tasks):
        calls.append(task)
        return [verifier.Grade(True, "done", {"a": True})]

    monkeypatch.setattr(verifier, "grade_snapshots", fake)
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "f.txt").write_text("same")
    ex = state_replay.DockerReplay()
    assert ex.grade("t", tmp_path / "one") == ex.grade("t", tmp_path / "two")
    assert calls == ["t"]
    (tmp_path / "two" / "f.txt").write_text("changed")
    ex.grade("t", tmp_path / "two")
    assert calls == ["t", "t"]


def test_failed_replay_is_empty_and_logged(tmp_path):
    ex = state_replay.DockerReplay()
    assert ex.replay(tmp_path, [ToolEvent(tool="terminal", cmd="true")]) == []
    assert ex.failures == ["replay before any grade: task unknown"]
