# Phase 1b note

**2026-10-05. Phase 1b configuration, stages and cost, frozen under Amendment 2 before any
Phase 1b trial.** This is the note Amendments 1 and 2 of `configs/prereg.md` require. The commit
that adds it is the Phase 1b freeze. Phase 1b runs on its parent, the code commit
`aa4653d95d42310c631455f88ce96cdc70f72044`. The primary verifier was frozen at `9df0a0e`.

*Configuration, unchanged from Phase 1a.* Job settings match the archived
`jobs/phase1-weak/config.json`, except for the task selection and attempt count.
- Weak agent arm: `z-ai/glm-5.3-flash` on OpenRouter, pinned to `z-ai`, fallbacks disabled.
- Hermes at `ffc74885c5f6eb75f6c134fb4eef86d734066623`. Harbor 0.23.0, with the same prebuilt
  images and Docker environment (`harness/egress/docker-desktop-dns.yaml`).
- Harness defaults as in Phase 1a: six goal turns, 600 s per turn, no soak mode, 6 concurrent
  trials.
- In-loop judge: `prod-plain:self-weak:head4k` (GLM-5.3-Flash, same route), temperature 0,
  max_tokens 4096, no reasoning configuration.
- `hjr/harness/` is identical to `73820f2`, the Phase 1a code, and the judge request it sends is
  unchanged. What changed since then is ingest and analysis, which run after the trials.
- No retries, as in Phase 1a and Amendment 2 (Harbor's `--max-retries` defaults to 0). Every
  failed trial is excluded with its reason.
  - Turn timeouts surface as `RuntimeError: Command timed out after 600 seconds`, so they are
    excluded like any other failed trial.
  - A trial in which any agent or judge call failed for good is excluded whole by `hjr ingest`
    with reason `provider_error`. This covers 402, 429 after retries, 5xx and a refused key.
    The exclusion records which calls failed and whether it is spend-stop shortfall (402). An
    agent stopped by its provider would otherwise read as verifier-not-done.
  - A call that recovers on retry does not exclude its trial.
  - No Phase 1a trial in either arm shows a provider error.
- Records carry `phase = "1b-enrichment"`. `hjr ingest` refuses any other phase for a
  `phase1b-*` job.
- Truth is the frozen primary verifier. Each stage's frozen file is regraded with `hjr regrade`,
  and every boundary must have a regraded row.

*Tasks.* The 16 C2–C4 tasks, with their frozen splits. Held-out trajectories stay unread before
`repair-freeze-v1`. Stage B selection reads only boundary ids, task, category, split and phase,
plus regraded truth.

| Task | Split | Phase 1a not done / attempts (primary) |
|---|---|---|
| `c2-01-rename-function` | dev | 0/3 |
| `c2-02-add-dry-run-flag` | heldout | 0/3 |
| `c2-03-release-bump` | heldout | 0/3 |
| `c2-04-settings-migration` | heldout | 0/3 |
| `c2-05-month-end-close` | dev | 0/3 |
| `c3-01-missing-interpreter` | heldout | 0/3 |
| `c3-02-missing-sqlite` | heldout | 0/3 |
| `c3-03-flaky-sync` | dev | 0/3 |
| `c3-04-stale-lock` | heldout | 0/3 |
| `c3-05-missing-yaml` | heldout | 0/3 |
| `c3-06-silent-empty-export` | dev | 0/3 |
| `c4-01-fix-git` | heldout | 0/3 |
| `c4-02-sqlite-db-truncate` | dev | 0/3 |
| `c4-03-cobol-modernization` | heldout | 1/3 |
| `c4-04-regex-log` | dev | 0/3 (2 excluded) |
| `c4-05-log-summary-date-ranges` | heldout | 0/3 |

*What Stage A can detect.* From `hjr phase1b-estimate`: the probability that a task shows at
least one not-done boundary in 20 attempts, given its true per-attempt rate. It assumes
independent attempts. It is a planning figure, not a forecast.

| True not-done rate | P(≥1 not done in 20 attempts) |
|---|---|
| 2% | 0.332392 |
| 5% | 0.641514 |
| 10% | 0.878423 |
| 20% | 0.988471 |

*Stage A.* 20 attempts on each of the 16 tasks, 320 scheduled trials, job `phase1b-weak-a`.
The dedicated key must be set. Harbor and `hjr` both load the main `OPENROUTER_API_KEY` from
`.env`, but neither overrides a variable already in the environment. Without the guard, the run
would silently use the uncapped key.

```bash
: "${OPENROUTER_API_KEY_PHASE1B:?dedicated Phase 1b key not set}"
export HJR_ROOT="$PWD"
EK='extra_docker_compose=["harness/egress/docker-desktop-dns.yaml"]'
OPENROUTER_API_KEY="$OPENROUTER_API_KEY_PHASE1B" \
  uv run --no-sync harbor run -p tasks/ -e docker --ek "$EK" \
  -i 'c2-*' -i 'c3-*' -i 'c4-*' -k 20 -n 6 -o jobs --job-name phase1b-weak-a \
  --agent-import-path hjr.harness.agent:HermesGoalLoop --ak arm=weak
uv run --no-sync hjr ingest --job jobs/phase1b-weak-a --phase 1b-enrichment \
  --out data/frozen/phase1b-weak-a.jsonl
uv run --no-sync hjr regrade data/frozen/phase1b-weak-a.jsonl
```

*Stage B.* 40 more attempts on each task that `hjr phase1b-select` returns, and on no other
task. That is every C2–C4 task with at least one primary-truth not-done boundary in Stage A.
Job `phase1b-weak-b`. If the list is empty, Stage B does not run.

```bash
: "${OPENROUTER_API_KEY_PHASE1B:?dedicated Phase 1b key not set}"
export HJR_ROOT="$PWD"
EK='extra_docker_compose=["harness/egress/docker-desktop-dns.yaml"]'
mapfile -t TASKS < <(uv run --no-sync hjr phase1b-select --stage-a data/frozen/phase1b-weak-a.jsonl)
if (( ${#TASKS[@]} == 0 )); then
  echo "no Stage B tasks; Stage B does not run"  # never run without -i: that is every task
else
  INCLUDE=(); for t in "${TASKS[@]}"; do INCLUDE+=(-i "$t"); done
  OPENROUTER_API_KEY="$OPENROUTER_API_KEY_PHASE1B" \
    uv run --no-sync harbor run -p tasks/ -e docker --ek "$EK" \
    "${INCLUDE[@]}" -k 40 -n 6 -o jobs --job-name phase1b-weak-b \
    --agent-import-path hjr.harness.agent:HermesGoalLoop --ak arm=weak
  uv run --no-sync hjr ingest --job jobs/phase1b-weak-b --phase 1b-enrichment \
    --out data/frozen/phase1b-weak-b.jsonl
  uv run --no-sync hjr regrade data/frozen/phase1b-weak-b.jsonl
fi
```

*Cost estimate.* Source: the 46 Phase 1a weak-arm trials on these tasks. Agent figures come
from their session summaries (`jobs/phase1-weak/*/agent/session_01.jsonl`), judge figures from
their in-loop verdicts (`agent/turns.jsonl`). Only numeric fields were read.

| Per trial | Mean | Median | Max | Basis |
|---|---|---|---|---|
| Agent and auxiliary calls | $0.007032 | $0.005826 | $0.031326 | Hermes estimate at list price (`cost_status = estimated`), not billed |
| In-loop judge (one call per trial in Phase 1a) | $0.000302 | $0.000190 | $0.001487 | provider-reported `usage.cost` |

| Scenario | Trials | Estimate |
|---|---|---|
| Stage A | 320 | $2.35 ($2.25 agent, $0.10 judge) |
| Stage B, `c4-03` only (its Phase 1a agent mean is $0.019525) | 40 | $0.79 |
| Stage B, all 16 tasks | 640 | $4.69 |
| Both stages, all 16 tasks | 960 | $7.04 |
| Both stages, every trial at the observed per-trial maximum | 960 | $31.50 |

Not covered by these figures:
- Timed-out trials have no usage record. Two of three `c4-04` attempts timed out in Phase 1a.
  Its one completed attempt used 17,415 output tokens on its first call.
- Billed amounts may differ from Hermes's list-price estimate.

*Spend stop.* A dedicated OpenRouter key with a $20 credit limit, read from
`OPENROUTER_API_KEY_PHASE1B`, carries every paid Phase 1b call: agent, auxiliary and in-loop
judge. The limit is separate from the $20 Phase 2 stop. If it is reached mid-stage:
- completed trials are kept;
- unscheduled trials are not run;
- trials cut off by a 402 are excluded as `provider_error` with `shortfall = true`;
- the shortfall is reported.

*Analysis.* As in Amendment 2:
- Truth-conditional metrics only, micro- and task-macro-averaged, with task-bootstrap intervals.
- Diversity reported as distinct tasks with not-done boundaries, with each task's share.
- With fewer than 5 such tasks, per-task counts and judge decisions only, with no pooled rate or
  interval.
- Stage A rates, Stage B counts and the Stage B selection are reported.
- Never pooled with Phase 1a.

**TODO before any Phase 1b analysis:** the analysis code has neither task-macro averages nor the
fewer-than-5-tasks rule. Both must be implemented and tested before any Phase 1b result is
computed.
