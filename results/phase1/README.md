# Phase 1: trajectories (G-plain)

Protocol: the amendments of 2026-10-02 in `configs/prereg.md`. Both jobs ran on code at
`73820f2` (clean tree): 30 tasks × 3 attempts per agent arm, `-k 3 -n 6`, six-turn budget, the
in-loop judge being each arm's `self` judge with the production prompt and `head4k` view.
Boundaries were ingested at `9fd7d51`, which changes only reporting code. The frozen records
are `data/frozen/phase1-{weak,strong}.jsonl`, each with its exclusions and a provenance
manifest. Full job directories ship as release assets.

| Arm | Job | Ran (UTC, 2026-10-02) | Trials | Errored | Boundaries | Excluded |
|---|---|---|---|---|---|---|
| weak (GLM-5.3-Flash, Z.AI) | `phase1-weak` | 13:49–14:27 | 90 | 2 | 88 | 2 |
| strong (DeepSeek V4.1 Flash, DeepSeek) | `phase1-strong` | 14:27–14:48 | 90 | 0 | 90 | 0 |

**Exclusions.** Both are weak-arm `c4-04-regex-log` trials whose first turn hit the 600 s turn
limit. Their first model call was still streaming: the arm's one completed trial on that task
spent 7 min 43 s and 17,415 output tokens on its first call. This is the agent's behaviour under
the frozen limit, not an infrastructure failure, so the trials were not retried. They have no
boundary and are listed in `phase1-weak.excluded.json`.

## What the data contain

These are counts of in-loop decisions against verifier truth, reported before any Phase-2
analysis. The in-loop judge is the production configuration, so these are the cells that
H1 is about. Rates, intervals and comparisons belong to Phase 2.

| Arm | DONE, truth done | DONE, truth not done | BLOCKED, truth blocked | Other |
|---|---|---|---|---|
| weak | 69 | 7 | 12 | 0 |
| strong | 69 | 9 | 12 | 0 |

- Every trial ended after its first turn, so each trial gives one boundary (178 in all, against
  the plan's expectation of 2–3 per trial).
- All 16 not-done boundaries were judged DONE. They come from 5 tasks: `c2-01` and `c6-02`
  (3 per arm), `c6-04` (2, strong), `c4-03` (1, weak) and `c4-05` (1, strong).
- No final response exceeded 4,000 characters (longest: 1,959 weak, 2,757 strong), so the
  production `head4k` view truncated nothing. The truncation effect seen in the pilot is not
  exercised by these trajectories.
- Splits: weak 34 dev / 54 held-out; strong 36 dev / 54 held-out.
