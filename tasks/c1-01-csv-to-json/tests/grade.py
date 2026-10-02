"""Grade the final workspace and every turn-boundary snapshot of one trial.

Runs inside the separate, network-less verifier container. Each task ships a copy of this file
next to its own check_state.py (tests/test_tasks.py keeps the copies identical). Truth for a
workspace is `done` when every requirement holds. Otherwise it is `not_done`, or `blocked` for an
infeasible task (one whose check_state sets INFEASIBLE, so that some requirement can never hold).

Writes /logs/verifier/boundaries.json (per-boundary detail) and reward.json (Harbor's reward).
"""

import json
import tarfile
import tempfile
from pathlib import Path

import check_state
from check_state import check

WORKSPACE = Path("/app")
BOUNDARIES = Path("/logs/artifacts/boundaries")
OUT = Path("/logs/verifier")


def grade(ws: Path) -> dict:
    requirements = check(ws)
    if all(requirements.values()):
        truth = "done"
    else:
        truth = "blocked" if getattr(check_state, "INFEASIBLE", False) else "not_done"
    return {"truth_state": truth, "requirements": requirements}


def grade_snapshot(tgz: Path) -> dict:
    with tempfile.TemporaryDirectory() as d:
        with tarfile.open(tgz) as tf:
            tf.extractall(d, filter="data")
        return {"snapshot": tgz.name, "turn": int(tgz.name[1:3]), **grade(Path(d))}


def main() -> None:
    final = grade(WORKSPACE)
    boundaries = [grade_snapshot(p) for p in sorted(BOUNDARIES.glob("b[0-9][0-9].tgz"))]
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"final": final, "boundaries": boundaries}
    (OUT / "boundaries.json").write_text(json.dumps(report, indent=2) + "\n")
    reward = {"reward": int(final["truth_state"] == "done")}
    reward |= {f"req_{k}": int(v) for k, v in final["requirements"].items()}
    (OUT / "reward.json").write_text(json.dumps(reward) + "\n")


if __name__ == "__main__":
    main()
