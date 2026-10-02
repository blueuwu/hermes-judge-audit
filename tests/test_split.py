from collections import Counter
from pathlib import Path

from hjr.config import global_seed
from hjr.split import SPLIT_CONFIG, load_split, make_split, render

TASKS = Path(__file__).resolve().parents[1] / "tasks"


def test_committed_split_is_the_generator_output():
    seed = global_seed()
    assert SPLIT_CONFIG.read_text(encoding="utf-8") == render(make_split(TASKS, seed), seed)


def test_split_is_stratified_by_category_and_skips_soak_tasks():
    split = load_split()
    assert "hjr/s0-01-incident-review" not in split
    by_category = Counter((task.split("/")[1][:2], s) for task, s in split.items())
    for category in {c for c, _ in by_category}:
        n = by_category[(category, "dev")] + by_category[(category, "heldout")]
        assert by_category[(category, "dev")] == round(n * 0.4)


def test_a_category_shuffle_does_not_depend_on_other_categories(tmp_path):
    seed = global_seed()
    for task in TASKS.glob("c[1-5]-*/task.toml"):
        dest = tmp_path / task.parent.name
        dest.mkdir()
        (dest / "task.toml").write_bytes(task.read_bytes())
    without_c6 = make_split(tmp_path, seed)
    full = make_split(TASKS, seed)
    assert all(full[t] == s for t, s in without_c6.items())
