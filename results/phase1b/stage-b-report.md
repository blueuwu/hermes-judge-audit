# Phase 1b Stage B report

**2026-10-06. Metadata-only report on job `phase1b-weak-b`, run per the Phase 1b note
(`results/phase1b/note.md`, frozen at `c0cd890`), `results/phase1b/deviation-1.md` and the
Stage B selection in `results/phase1b/stage-a-report.md`.** It records counts, exit codes, route
metadata and spend. It computes no Phase 1b metric and no judge-accuracy figure. No trajectory,
response, session or judge-reason content was read. `results/regrade/phase1b-weak-b.md` was
written by `hjr regrade` and was not opened.

## Run

- Start commit `16a914b`, clean tree, `hjr/harness/` identical to `73820f2`, Harbor 0.23.0
  unpatched.
- Launched with `PYTHONUTF8=1` in the launch environment. `uv run --no-sync hjr preflight`
  passed immediately before launch.
- Started 2026-10-06T14:09:13Z, ended 2026-10-06T15:35:11Z. Harbor exited 0. There were no
  retries, no cancellations and no harness crash, so the deviation-1 crash rule did not fire.
- 200 trials scheduled (5 tasks x 40 attempts) and 200 run. Harbor recorded 5 trial errors, all
  `RuntimeError: Command timed out after 600 seconds`.
- The job config lists exactly the 5 selected tasks, with `n_attempts` 40, 6 concurrent trials
  and agent kwargs `{"arm": "weak"}`.

## Launch-wrapper deviation

The note's Stage B command reads the task list with
`mapfile -t TASKS < <(uv run --no-sync hjr phase1b-select ...)`. On Windows, `hjr
phase1b-select` ends each line with `\r\n`. `mapfile -t` removes the `\n` and keeps the `\r`, so
every task ID gets a trailing `\r` (`$'c2-01-rename-function\r'`) and every `-i` filter passed to
Harbor carries it.

The first launch attempt, with the 13:56:14Z baseline, stopped at a check in the launch wrapper.
The check compares the list with the 5 committed task IDs, and it failed before `harbor run`.
No job directory was created, no container ran and nothing was spent.

The fix strips the carriage returns and changes nothing else:

```bash
mapfile -t TASKS < <(uv run --no-sync hjr phase1b-select --stage-a data/frozen/phase1b-weak-a.jsonl | tr -d '\r')
```

The exact-match check against the 5 committed IDs stayed in place and passed. The fix does not
touch Harbor, the harness or any setting. The selection command, its output, the attempt count,
the concurrency and the agent arguments are as in the note.

## Per task

"No-boundary trials" are the 5 timeout trials. In each, the agent never finished a turn, so the
trial produced no boundary. They are not analytical exclusions. The ingest step lists them in
`data/frozen/phase1b-weak-b.excluded.json` with reason `no turns.jsonl (agent never finished a
turn)`, and that frozen file is left as written. Not-done counts are primary truth from
`hjr regrade`.

| Task | Split | Attempts | No-boundary trials | Boundaries | Not done |
|---|---|---|---|---|---|
| `c2-01-rename-function` | dev | 40 | 0 | 40 | 11 |
| `c2-03-release-bump` | heldout | 40 | 0 | 41 | 2 |
| `c2-05-month-end-close` | dev | 40 | 0 | 40 | 4 |
| `c4-03-cobol-modernization` | heldout | 40 | 5 | 35 | 8 |
| `c4-05-log-summary-date-ranges` | heldout | 40 | 0 | 40 | 1 |
| **Total** | | **200** | **5** | **196** | **26** |

- 195 trials produced at least one boundary. `c2-03-release-bump` produced 41 boundaries from
  40 trials.
- 0 `provider_error` exclusions and no shortfall.
- `hjr ingest --phase 1b-enrichment` wrote 196 boundaries, all with phase `1b-enrichment`.
  `hjr regrade` wrote 196 rows to `data/truth/phase1b-weak-b.jsonl`, one per boundary, with
  none missing and none extra.

## Route checks

Every completed trial was checked by the watcher at the three levels set in deviation-1. No
deviation was found and the run was not halted.

| Level | Calls | Result |
|---|---|---|
| Agent main loop, verified via `/generation` | 1,731 | 1,731/1,731 returned `z-ai/glm-5.3-flash-20260826` on `Z.AI`, configured route `openrouter` with `z-ai/glm-5.3-flash`, logged upstream `Z.AI` |
| In-loop judge, self-reported | 196 | all `z-ai/glm-5.3-flash` on `Z.AI` |
| Auxiliary, configured route only | 802 lines | all `openrouter` with `z-ai/glm-5.3-flash`, at least one in every trial; returned model and provider unverifiable |

During the run, 1,725 agent lookups were verified when the trial completed. The other 6 had no
`/generation` record yet. All 6 were looked up again after the run and returned the same model
and provider.

## Spend

Readings from OpenRouter's `/api/v1/key` for the dedicated Phase 1b key, which has a $20 cap.

| Reading | Time (UTC) | Usage |
|---|---|---|
| Stage A end, as reported | 2026-10-06T12:45:15Z | $2.595753 |
| Stage B baseline | 2026-10-06T14:08:55Z | $2.606240 |
| Stage B end | 2026-10-06T15:37:12Z | $4.537022 |
| **Stage B** | | **$1.930782** |

- Stage B is about $0.0097 per trial. The note has no estimate for this set of 5 tasks.
- The first Stage B baseline, at 13:56:14Z before the wrapper fix, read the same $2.606240.
  Nothing was spent between it and the second baseline.
- **Stage A spend revised to $2.568193.** The $0.010487 billed between the Stage A end reading
  (12:45:15Z) and the Stage B baseline is late-billed Stage A charges, since no other job ran on
  the key in between. That is about $0.0080 per trial, 9.3% over the note's $2.35 estimate.
- $15.462978 of the cap remains. Usage on the key, $4.537022, covers the aborted first Stage A
  launch (deviation-1), Stage A and Stage B.

## Timeouts against Phase 1a and Stage A

Counts of trials whose `exception_info` reports `Command timed out after 600 seconds`, read
from each trial's `result.json`.

| Task | Phase 1a weak | Stage A | Stage B |
|---|---|---|---|
| `c4-03-cobol-modernization` | 0 of 3 | 2 of 20 | 5 of 40 |
| `c4-04-regex-log` | 2 of 3 | 12 of 20 | not selected |
| Other selected tasks | 0 of 3 each | 0 of 20 each | 0 of 40 each |

The `c4-04` timeout rate matches Phase 1a (2 of 3 against 12 of 20), with identical timeout
configuration and call path, as established in the Stage A report.
- All 5 Stage B timeouts go through the same harness and Harbor frames as the Phase 1a and
  Stage A timeouts: `agent.py` lines 298 and 186, then `docker.py` line 730.
- The Stage B job's agent kwargs are `{"arm": "weak"}` with no agent env, as in both earlier
  jobs.
