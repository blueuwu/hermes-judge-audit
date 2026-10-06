# Phase 1b Stage A report

**2026-10-06. Metadata-only report on job `phase1b-weak-a`, run per the Phase 1b note
(`results/phase1b/note.md`, frozen at `c0cd890`) and `results/phase1b/deviation-1.md`.** It
records counts, exit codes, route metadata and spend. It computes no Phase 1b metric and no
judge-accuracy figure. No trajectory, response, session or judge-reason content was read.
`results/regrade/phase1b-weak-a.md` was written by `hjr regrade` and was not opened.

## Run

- Start commit `d9e63a8`, clean tree, `hjr/harness/` identical to `73820f2`, Harbor 0.23.0
  unpatched.
- Launched with `PYTHONUTF8=1` in the launch environment. `uv run --no-sync hjr preflight`
  passed immediately before launch.
- Started 2026-10-06T10:17:40Z, ended 2026-10-06T12:43:29Z. Harbor exited 0. There were no
  retries and no harness crash, so the deviation-1 crash rule did not fire.
- 320 trials scheduled (16 tasks x 20 attempts) and 320 run. Harbor recorded 14 trial errors,
  all `RuntimeError: Command timed out after 600 seconds`.

## Per task

"No-boundary trials" are the 14 timeout trials. In each, the agent never finished a turn, so the
trial produced no boundary. They are not analytical exclusions. The ingest step lists them in
`data/frozen/phase1b-weak-a.excluded.json` with reason `no turns.jsonl (agent never finished a
turn)`, and that frozen file is left as written. Not-done counts are primary truth from
`hjr regrade`.

| Task | Split | Attempts | No-boundary trials | Boundaries | Not done |
|---|---|---|---|---|---|
| `c2-01-rename-function` | dev | 20 | 0 | 20 | 5 |
| `c2-02-add-dry-run-flag` | heldout | 20 | 0 | 20 | 0 |
| `c2-03-release-bump` | heldout | 20 | 0 | 20 | 2 |
| `c2-04-settings-migration` | heldout | 20 | 0 | 20 | 0 |
| `c2-05-month-end-close` | dev | 20 | 0 | 20 | 3 |
| `c3-01-missing-interpreter` | heldout | 20 | 0 | 20 | 0 |
| `c3-02-missing-sqlite` | heldout | 20 | 0 | 20 | 0 |
| `c3-03-flaky-sync` | dev | 20 | 0 | 20 | 0 |
| `c3-04-stale-lock` | heldout | 20 | 0 | 20 | 0 |
| `c3-05-missing-yaml` | heldout | 20 | 0 | 23 | 0 |
| `c3-06-silent-empty-export` | dev | 20 | 0 | 20 | 0 |
| `c4-01-fix-git` | heldout | 20 | 0 | 20 | 0 |
| `c4-02-sqlite-db-truncate` | dev | 20 | 0 | 20 | 0 |
| `c4-03-cobol-modernization` | heldout | 20 | 2 | 18 | 8 |
| `c4-04-regex-log` | dev | 20 | 12 | 9 | 0 |
| `c4-05-log-summary-date-ranges` | heldout | 20 | 0 | 20 | 1 |
| **Total** | | **320** | **14** | **310** | **19** |

- 306 trials produced at least one boundary. `c3-05-missing-yaml` produced 23 boundaries from
  20 trials, and `c4-04-regex-log` 9 boundaries from 8 trials.
- 0 `provider_error` exclusions and no shortfall.
- `hjr ingest --phase 1b-enrichment` wrote 310 boundaries, all with phase `1b-enrichment`.
  `hjr regrade` wrote 310 rows to `data/truth/phase1b-weak-a.jsonl`, one per boundary, with
  none missing and none extra.

## Route checks

Every completed trial was checked by the watcher at the three levels set in deviation-1. No
deviation was found and the run was not halted.

| Level | Calls | Result |
|---|---|---|
| Agent main loop, verified via `/generation` | 2,165 | 2,165/2,165 returned `z-ai/glm-5.3-flash-20260826` on `Z.AI`, configured route `openrouter` with `z-ai/glm-5.3-flash`, logged upstream `Z.AI` |
| In-loop judge, self-reported | 310 | all `z-ai/glm-5.3-flash` on `Z.AI` |
| Auxiliary, configured route only | 1,288 lines | all `openrouter` with `z-ai/glm-5.3-flash`, at least one in every trial; returned model and provider unverifiable |

During the run, 2,144 agent lookups were verified when the trial completed. The other 21 had
no `/generation` record yet. All 21 were looked up again after the run and returned the same
model and provider.

## Spend

Readings from OpenRouter's `/api/v1/key` for the dedicated Phase 1b key, which has a $20 cap.

| Reading | Time (UTC) | Usage |
|---|---|---|
| Baseline | 2026-10-06T10:17:32Z | $0.038047 |
| End | 2026-10-06T12:45:15Z | $2.595753 |
| **Stage A** | | **$2.557706** |

That is about $0.0080 per trial, 8.8% over the note's $2.35 estimate. $17.404247 of the cap
remains. The baseline includes the aborted first launch (deviation-1).

## Stage B selection

```
uv run --no-sync hjr phase1b-select --stage-a data/frozen/phase1b-weak-a.jsonl
```

Exit code 0. Selected tasks:

- `c2-01-rename-function`
- `c2-03-release-bump`
- `c2-05-month-end-close`
- `c4-03-cobol-modernization`
- `c4-05-log-summary-date-ranges`

## Phase 1a timeout parity

Counts of trials whose `exception_info` reports `Command timed out after 600 seconds`, read
from each trial's `result.json`. No other task timed out in either run, and Phase 1a strong had
no timeouts.

| Task | Phase 1a weak | Phase 1b Stage A |
|---|---|---|
| `c4-03-cobol-modernization` | 0 of 3 | 2 of 20 |
| `c4-04-regex-log` | 2 of 3 | 12 of 20 |
| Other 14 C2 to C4 tasks | 0 of 3 each | 0 of 20 each |

The timeout configuration is the same in both runs. This was checked against source and config,
not inferred:

- The 600 seconds is `turn_timeout_sec`, the per-turn wall clock in `HermesGoalLoop`
  (`hjr/harness/agent.py`, default 600). The agent passes it to Harbor's docker `exec`, which
  raises this error (`harbor/environments/docker/docker.py`, line 730).
- Neither job overrides it. In both `jobs/phase1-weak/config.json` and
  `jobs/phase1b-weak-a/config.json` the agent kwargs are exactly `{"arm": "weak"}`, with no
  agent env.
- Phase 1a launched at 2026-10-02 19:19:59 +0530, on commit `73820f2`. `hjr/harness/` at
  `d9e63a8` is identical to `73820f2`. No C2 to C4 `task.toml` changed between the two commits,
  so the task-level agent timeout (`timeout_sec = 900.0` for both C4 tasks) is unchanged. The
  only C2 to C4 task changes are the verifier v2 test files for `c2-01` and `c2-03` (`67559d5`),
  which do not set timeouts.
- Harbor 0.23.0's installed files date from 2026-10-01 and were unpatched in both runs.
- The two Phase 1a timeouts and all 14 Stage A timeouts have the same harness and Harbor
  traceback frames: `agent.py` lines 298 and 186, then `docker.py` line 730.
