# Running the study on Harbor

What worked and what broke running this study on Harbor **0.23.0**, the version pinned in
`pyproject.toml` and resolved in `uv.lock`. I have not checked whether the problems below
persist in later releases.

Counts come from `scripts/harbor_failure_counts.py`, run over the local job directories on
2026-10-14. It uses only the standard library, reads jobs without writing, and makes no network
or model calls:

```text
python scripts/harbor_failure_counts.py --jobs-dir <local-jobs-root>
```

## Setup

The `/goal` loop is my own Harbor agent (`hjr.harness.agent:HermesGoalLoop`), not something
Harbor ships. It resumes one Hermes session per turn and snapshots the workspace at every turn
boundary. A separate verifier container grades the final workspace and each snapshot, so the
hidden checks never enter the agent's image. Harbor's environment and custom-agent interfaces
allowed all of this without patching Harbor, and its per-trial records made failures auditable
after the runs.

## Job counts

Total is the number of scheduled trials, Present the trial directories that materialized.
Failed counts execution failures (explicit errors, unrecovered provider errors, trials with no
result), not tasks the agent got wrong. The four cause columns split Failed; a trial with several
signals is counted once, by the script's precedence. Agent arms are kept separate.

| Job | Total | Present | Failed | Harbor | Provider | Timeout | Unclassified |
|---|---:|---:|---:|---:|---:|---:|---:|
| oracle-suite | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| smoke-weak-2 | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| phase1-weak | 90 | 90 | 2 | 0 | 0 | 2 | 0 |
| phase1-strong | 90 | 90 | 0 | 0 | 0 | 0 | 0 |
| phase1b-weak-a-attempt1 | 320 | 7 | 7 | 5 | 0 | 0 | 2 |
| phase1b-weak-a | 320 | 320 | 14 | 0 | 0 | 14 | 0 |
| phase1b-weak-b | 200 | 200 | 5 | 0 | 0 | 5 | 0 |

The script also prints the development jobs (`smoke-strong-*`, `mech-*`, `oracle-dev*`,
`netprobe5`); their failures are described below. The jobs had different purposes, so these
counts are not a Harbor failure rate, and a job with zero matched failures can still have had
an incident that left no recognized record.

## What broke

**A decoding error ended a whole job.** A `UnicodeDecodeError` in Harbor 0.23.0, reading a
UTF-8 session file as cp1252, ended the 320-trial job `phase1b-weak-a-attempt1`. Its archive has
5 decoding exceptions, 1 cancellation and 1 trial with no result; the other 313 trials never
started. That is one aborted job, not 320 failures. The rerun with `PYTHONUTF8=1`,
`phase1b-weak-a`, ran all 320 ([deviation 1](../results/phase1b/deviation-1.md)). What would
help: decode subprocess output defensively and keep the raw bytes, turn a decoding failure into
an error on that trial so the rest of the queue keeps running, and when the scheduler does
stop, record why and the final state of every scheduled trial.

**Provider failures behind a clean exit.** `smoke-strong-1` had 2 trials end on provider errors
(`smoke-strong-2` had none), and `mech-1`, `mech-net` and `mech-s0` had 1 each. These were
failures of my integration, not a Harbor defect. A way for a custom agent to report a terminal
provider failure in the trial result, with the exception class and HTTP status, would stop a
wrapper that exits cleanly from hiding a failed goal loop.

**Verifier handoff.** `oracle-dev2` had 2 `RewardFileNotFoundError` failures; `oracle-dev` had
2 unclassified failures and `netprobe5` 1. A missing reward file shows that the handoff to the
verifier failed, not which side caused it. Checking the verifier's output contract early, and
tagging failures by stage (setup, execution, collection), would settle that. The other
exceptions stay unclassified: a generic exception with Harbor in its stack trace is not enough
to blame Harbor.

## Timeouts

All 21 classified timeouts are in weak-arm jobs: 14/320 in `phase1b-weak-a`, 5/200 in
`phase1b-weak-b` and 2/90 in `phase1-weak`. No strong-arm job had one. Each matches Harbor's
Docker command-timeout marker, and each came on the first turn, before any boundary: 14 on
`c4-04-regex-log` (2 in `phase1-weak`, 12 in `phase1b-weak-a`) and 7 on
`c4-03-cobol-modernization` (2 in `phase1b-weak-a`, 5 in `phase1b-weak-b`).

The analysis excludes them like any other failed trial, under the Phase 1b note
(`results/phase1b/note.md`, frozen 2026-10-05) and Amendment 2 of `configs/prereg.md`: no
retries, and every exclusion listed with its reason in `data/frozen/*.excluded.json` and the
Stage A and Stage B reports under `results/phase1b/`.

The marker says which layer reported the timeout, not whether the delay came from the model,
the sandbox or verification. Recording the operation, configured timeout, elapsed time and
cleanup outcome as structured fields would separate slow commands from orchestration stalls.

## Retries

Nothing in these jobs was retried. Harbor's retry count is 0 in every job, and the saved `hjr`
judge attempt records show 0 retry invocations, so the counts say nothing about recovery by
retry. The script reports `hjr` retries separately from terminal causes. In Harbor's own
reporting it would help to expose who retried, the attempt number, the final outcome and whether
a retry actually ran; a retryable flag alone should not count as a retry.
