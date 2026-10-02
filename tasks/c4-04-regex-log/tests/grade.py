"""Grade the final workspace and every turn-boundary snapshot of one trial.

Runs inside the separate, network-less verifier container. Each task ships a copy of this file
next to its own check_state.py (tests/test_tasks.py keeps the copies identical). Truth for a
workspace is `done` when every requirement holds. Otherwise it is `not_done`, or `blocked` for an
infeasible task: one whose check_state names, in INFEASIBLE, the requirements that cannot hold
without something the agent does not have. Harbor's reward for an infeasible task is whether the
feasible requirements hold, so its reference solution does the feasible part and stops.

Writes /logs/verifier/boundaries.json (per-boundary detail) and reward.json (Harbor's reward).
"""

import json
import tarfile
import tempfile
from pathlib import Path

from check_state import check

try:
    from check_state import INFEASIBLE
except ImportError:
    INFEASIBLE = ()

WORKSPACE = Path("/app")
BOUNDARIES = Path("/logs/artifacts/boundaries")
OUT = Path("/logs/verifier")


def grade(ws: Path) -> dict:
    requirements = check(ws)
    truth = "blocked" if INFEASIBLE else "not_done"
    if all(requirements.values()):
        truth = "done"
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
    requirements = final["requirements"]
    feasible = all(v for k, v in requirements.items() if k not in INFEASIBLE)
    reward = {"reward": int(feasible if INFEASIBLE else final["truth_state"] == "done")}
    reward |= {f"req_{k}": int(v) for k, v in requirements.items()}
    (OUT / "reward.json").write_text(json.dumps(reward) + "\n")


if __name__ == "__main__":
    main()
