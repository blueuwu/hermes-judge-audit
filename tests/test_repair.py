"""repair-v1 prompt and design set (prereg Amendment 3). No model calls."""

from __future__ import annotations

import re
import tomllib
from collections import Counter

import pytest

from hjr import judge, repair, repair_design
from hjr.codex import schema_valid
from hjr.config import ROOT
from hjr.repair_design import DesignItem, Score, score, select
from tests.factories import make_boundary


def test_example_shapes_parse_as_the_verdicts_they_show():
    shapes = [line for line in repair.SYSTEM_PROMPT.splitlines() if line.startswith('{"reason"')]
    assert len(shapes) == 6
    for line in shapes:
        filled = line.replace("<one sentence>", "x").replace('"<id>"', '"s1"').replace("<int>", "7")
        parsed = judge.parse_verdict(filled)
        assert parsed.outcome == "parsed"
        assert parsed.verdict == re.search(r'"verdict": "(\w+)"', line).group(1)


def test_codex_schema_accepts_reason_first():
    reply = (
        '{"reason": "x", "verdict": "done", '
        '"wait_on_session": null, "wait_on_pid": null, "wait_for_seconds": null}'
    )
    assert schema_valid(reply)


def test_prompt_names_nothing_from_the_design_set():
    split = tomllib.loads((ROOT / "configs" / "split.toml").read_text(encoding="utf-8"))
    text = (repair.SYSTEM_PROMPT + repair.USER_TEMPLATE).lower()
    for task in split["dev"] + split["heldout"]:
        name = task.split("/", 1)[1]
        assert name not in text
        assert name.split("-", 1)[1].replace("-", " ") not in text
    for word in (
        "calc_total",
        "compute_total",
        "manifest",
        "api.md",
        "changelog",
        "sha256",
        "docs_updated",
        "manifest_correct",
        "deprecat",
        "alias",
        "unreleased",
        "check_format",
    ):
        assert word not in text


def test_families_file_matches_the_design_set():
    families = repair_design.load_families()
    names = [f.name for f in families]
    assert len(names) == len(set(names))
    # Every id-listed family names design-set items that exist (family_rows checks the count).
    items = [
        _item("done", ["done"] * 3, source="p1b-a"),
    ]
    with pytest.raises(ValueError, match="ids not all"):
        repair_design.family_rows([f for f in families if f.ids][:1], {1: items})


def test_family_filters():
    fam = repair_design.Family("x", "", {"task": "t", "truth": "done"})
    assert fam.contains(_item("done", ["done"]))
    assert not fam.contains(_item("not_done", ["done"]))
    assert not fam.contains(_item("done", ["done"], source="pilot"))
    with pytest.raises(ValueError, match="unknown"):
        repair_design.Family("y", "", {"colour": "red"}).contains(_item("done", ["done"]))


def test_family_rows_count_errors_per_iteration():
    fam = repair_design.Family("x", "", {"truth": "done"})
    by_it = {1: [_item("done", ["continue"] * 3)], 2: [_item("done", ["done"] * 3)]}
    [(_, size, errors)] = repair_design.family_rows([fam], by_it)
    assert size == 1 and errors == {1: 1, 2: 0}


def test_write_report_keeps_the_prediction(tmp_path, monkeypatch):
    monkeypatch.setattr(
        repair_design, "report", lambda n, runs=None: f"## Results: iteration {n}\n"
    )
    out = tmp_path / "iteration-2.md"
    out.write_text("# repair-v1 design iteration 2\n\n## Prediction\n\nfewer errors\n")
    repair_design.write_report(2, out_dir=tmp_path)
    repair_design.write_report(2, out_dir=tmp_path)
    text = out.read_text()
    assert text.count("## Prediction") == 1 and text.count("## Results") == 1
    assert text.index("fewer errors") < text.index(repair_design.RESULTS_MARKER)


def test_user_prompt_keeps_production_fields():
    b = make_boundary(
        background_processes=[{"pid": 42, "command": "sleep 9", "status": "running"}],
        active_delegations=2,
    )
    user = judge.build_messages(b, prompt="repair-v1", view="evidence")[1]["content"]
    assert "pid 42" in user and "2 delegated subagent" in user and "Current time:" in user


def test_design_set_is_dev_only_and_matches_amendment_3():
    expected = {
        "pilot": {"done": 16, "not_done": 32},
        "p1a-weak": {"done": 28, "blocked": 6},
        "p1a-strong": {"done": 29, "not_done": 1, "blocked": 6},
        "p1b-a": {"done": 101, "not_done": 8},
        "p1b-b": {"done": 65, "not_done": 15},
    }
    for source, counts in expected.items():
        boundaries = repair_design.design_boundaries(source)
        assert {b.split for b in boundaries} == {"dev"}
        truth = repair_design.truth_states(source, boundaries)
        assert Counter(truth.values()) == counts


def test_iterations_are_capped_at_three():
    assert repair_design.run_id(3, "pilot") == "repair-i3-pilot"
    with pytest.raises(ValueError):
        repair_design.run_id(4, "pilot")


def _item(truth, decisions, source="p1b-a"):
    return DesignItem(source, "b", "t", truth, tuple(decisions), ("r",) * len(decisions))


def test_tie_is_not_done_and_counts_as_false_continue():
    item = _item("done", ["done", "continue", "blocked"])
    assert item.decision == "tie" and item.false_continue
    assert not _item("not_done", ["done", "continue", "blocked"]).false_done


def test_score_splits_natural_and_pilot():
    s = score(
        [
            _item("done", ["continue"] * 3),
            _item("blocked", ["done"] * 3),
            _item("not_done", ["done"] * 3, source="pilot"),
            _item("done", ["done"] * 3, source="pilot"),
        ]
    )
    assert (s.natural_false_continue, s.natural_done, s.natural_false_done, s.natural_not_done) == (
        1,
        1,
        1,
        1,
    )
    assert (s.pilot_false_done, s.pilot_not_done, s.pilot_false_continue) == (1, 1, 0)


def _score(fd, fc, pilot_fd=0, done=100):
    return Score(fd, 30, fc, done, pilot_fd, 32, 0, 16)


def test_selection_rule():
    # Fewest natural false-DONE within the bound; an iteration over the bound is not eligible.
    assert select({1: _score(5, 3), 2: _score(2, 9), 3: _score(4, 5)}) == 3
    # Ties: fewer pilot false-DONE, then the later iteration.
    assert select({1: _score(2, 0, pilot_fd=3), 2: _score(2, 0, pilot_fd=1)}) == 2
    assert select({1: _score(2, 0), 2: _score(2, 0)}) == 2
    # None within the bound: the lowest natural false-CONTINUE.
    assert select({1: _score(0, 9), 2: _score(4, 7)}) == 2
