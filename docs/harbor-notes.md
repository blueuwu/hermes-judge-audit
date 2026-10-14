# Running the study on Harbor

Observed: We used Harbor for sandboxed tasks, a custom agent running the Hermes `/goal`
loop, and separate verifier containers. The agent resumed a session for each turn and
saved workspace snapshots at turn boundaries. The verifier checked the final workspace
and those snapshots, with hidden checks kept out of the agent image. This describes our
integration, rather than a claim that Harbor supplies this goal loop itself.

Observed: The harness dependency is pinned to Harbor **0.23.0** in `pyproject.toml`, and
`uv.lock` resolves that same version. Those files were checked for this note. We have not
tested whether the problems below persist in another release.

In this note, **measured** means counted by `scripts/harbor_failure_counts.py` from the
available local jobs on 2026-10-14. **Observed** means an incident or implementation detail
inspected once, without an estimated frequency. **Inferred** means an interpretation or
engineering suggestion. The counter uses only the standard library, reads jobs without
writing, and makes no network or model calls. Run it with:

```text
python scripts/harbor_failure_counts.py --jobs-dir <local-jobs-root>
```

Measured: The following are selected per-job counts, with agent arms kept separate.
“Total” is the scheduled trial count. “Present” counts materialized trial directories.
“Failed” includes explicit execution errors, unrecovered provider errors, and materialized
trials missing a result. It does not count an unsuccessful task reward as an execution
failure. The four cause columns partition Failed; a trial with multiple signals is counted
once using the script's documented precedence.

| Job | Total | Present | Failed | Harbor | Provider | Timeout | Unclassified |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase1b-weak-a-attempt1 | 320 | 7 | 7 | 5 | 0 | 0 | 2 |
| phase1b-weak-a | 320 | 320 | 14 | 0 | 0 | 14 | 0 |
| phase1b-weak-b | 200 | 200 | 5 | 0 | 0 | 5 | 0 |
| phase1-weak | 90 | 90 | 2 | 0 | 0 | 2 | 0 |
| phase1-strong | 90 | 90 | 0 | 0 | 0 | 0 | 0 |
| oracle-suite | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| smoke-weak-2 | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| smoke-strong-1 | 2 | 2 | 2 | 0 | 2 | 0 | 0 |
| smoke-strong-2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| mech-1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 |
| mech-net | 1 | 1 | 1 | 0 | 1 | 0 | 0 |
| mech-s0 | 1 | 1 | 1 | 0 | 1 | 0 | 0 |
| netprobe5 | 1 | 1 | 1 | 0 | 0 | 0 | 1 |
| oracle-dev | 2 | 2 | 2 | 0 | 0 | 0 | 2 |
| oracle-dev2 | 2 | 2 | 2 | 2 | 0 | 0 | 0 |

## What worked

Observed: Harbor's environment and custom-agent interfaces let us add session resumption,
boundary snapshots, and independent verification without putting hidden checks in the agent
workspace. The saved trial records also made it possible to audit failures after the runs.

Measured: `oracle-suite` materialized 30 of 30 trials with zero classified execution
failures; `smoke-weak-2` did the same for 30 of 30. `phase1-strong` materialized 90 of 90
with zero classified execution failures. These counts establish that those jobs ran through
the harness; they do not establish that the model completed every task correctly.

Inferred: Keep these interfaces and the per-trial records stable. A small offline example
showing how to save a boundary snapshot and grade it in a separate container would help
other studies use the same separation.

## What broke and what would help

Observed: A `UnicodeDecodeError` in Harbor 0.23.0 killed the 320-trial job
`phase1b-weak-a-attempt1`. Measured: Its archive contains 5 Harbor-associated decoding
exceptions, 1 cancellation classified as unclassified, and 1 materialized trial without a
result, also unclassified. The other 313 scheduled trials did not materialize. This is one
aborted job, not 320 decoding failures. The later `phase1b-weak-a` materialized all 320 trials.

Inferred: Decode subprocess output defensively while retaining the original bytes for
diagnostics. Add a regression case containing invalid UTF-8 in subprocess output. An output
decoding failure should produce a structured trial error and allow unrelated queued trials
to continue. When the scheduler does stop, persist the cancellation reason and the final
state of every scheduled trial so incomplete work can be distinguished from failed work.

Measured: Explicit Harbor Docker command-timeout markers account for 2 failures in
`phase1-weak`, 14 in `phase1b-weak-a`, and 5 in `phase1b-weak-b`. Inferred: These markers
identify the execution layer that reported the timeout, but do not identify whether the
underlying delay came from the model, the sandbox, or verification. Persist the operation,
configured timeout, elapsed time, and cleanup outcome as structured fields. That would let
maintainers separate slow commands from environment or orchestration stalls without reading
private task content.

Measured: `smoke-strong-1` has 2 trials with terminal provider errors, while
`smoke-strong-2` has zero. `mech-1`, `mech-net`, and `mech-s0` each have 1 such trial.
Inferred: These are integration failures, not evidence of a Harbor provider defect. Give
custom agents an explicit way to report terminal provider failures in the trial result,
including the exception class and HTTP status, so a completed wrapper does not conceal a
failed goal loop.

Measured: `oracle-dev2` has 2 `RewardFileNotFoundError` failures. `oracle-dev` has 2
unclassified failures, and `netprobe5` has 1. Inferred: A missing reward file identifies a
verifier handoff failure but does not prove who caused it. Validate the verifier output
contract early and include structured setup, execution, and collection stages in failures.
The other exceptions remain unclassified because a generic exception with Harbor in its
call stack is insufficient evidence of ownership.

## Retry ownership and limits of the counts

Measured: The brief's assumption that retries in jobs/ belonged to hjr was wrong.
There are no hjr retries in the available jobs/, and Harbor's own retry count is 0
in every job too. The saved hjr judge attempt records contain 0 retry invocations
in each job. These counts do not measure recovery by retry. The counter reports
hjr retry trials and retry attempts separately from terminal causes.

Inferred: Preserve that distinction in Harbor's reporting: expose retry owner, attempt
number, terminal outcome, and whether a retry actually ran. A retryable flag alone should
not increment a retry counter.

Measured: The counter found no unreadable diagnostic records in these jobs. Unmatched
exceptions, cancellation, and missing trial results remain unclassified under explicit
rules. The script prints every discovered job, including the archived attempt, while this
note selects jobs relevant to the engineering issues. Inferred: These development,
smoke, oracle, and study jobs have different purposes; their counts should not be pooled
into a general Harbor failure rate. Zero matched failures also cannot rule out an incident
that left no recognized diagnostic record.
