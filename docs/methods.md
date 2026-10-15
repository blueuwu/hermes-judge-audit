# Methods, spend and logistics

Procedural detail for [`reports/report.md`](../reports/report.md): the tasks, the verifier, how
the judge cells were run, the pre-registration record and its deviations, trial exclusions,
reporting rules, the `repair-v1` selection, call reliability, the pilot and the full spend. Pre-registration:
[`configs/prereg.md`](../configs/prereg.md).

## Terms

The report's two zones, information-limited and attention-limited, are set by whether the failure
reaches the judge's input. This is separate from judge-model drift, which the prereg and
`hjr/drift.py` use for verdict changes between versions of the judge model.

## Tasks

30 tasks in six categories ([`tasks/README.md`](../tasks/README.md)):

| Category | Tasks | What it tests |
|---|---|---|
| C1 controls | 5 | Plain tasks the agent should finish |
| C2 multi-part | 5 | Goals with several requirements, one of which is easy to skip |
| C3 tool friction | 6 | Missing interpreters, flaky syncs, stale locks |
| C4 verification-required | 5 | Adapted from Terminal-Bench 2.0; the agent sees little or none of the checking |
| C5 infeasible | 4 | Goals that cannot be met without something the agent lacks |
| C6 long reports | 5 | Tasks whose answer is a long written report |

## Verifier

The verifier was tested before it was trusted. A mutation suite broke each requirement of each
task's reference solution in turn: 260 of 260 mutants were caught on the requirement they
targeted, and 33 of 33 benign variants passed. Two verifier defects found while reading failing
dev endpoints were fixed before the freeze. One `c2-01` check rejected reasonable work (adding a
test, documenting the alias the goal asked for), and one `c6-04` check expected a rule name the
task never gave. Fixing them moved 7 dev endpoints from not done to done. Every table is also
produced with the unfixed verifier as a sensitivity check.

## Verifier audit: the requirement-level error

The auditor found one requirement-level error, in a weak-arm `c5-03` endpoint in the "both say
not DONE" stratum: the agent's tests passed in its own environment, but the verifier's
`tests_pass` check failed, by the auditor's reading because its image lacked the agent's
installed packages. The endpoint label is unchanged and still correct, `blocked`, because the
requested package cannot be installed, so the stratum has 0 endpoint label errors. Counted as
the prereg's verifier error rate, which includes requirement-level errors, stratum C has 1 of 10
(Wilson 1.8 to 40.4%, [`results/audit/report.md`](../results/audit/report.md)).

## Judge cells

Production cells reproduce what Hermes sends byte for byte; a test checks every replayed prompt
against `judge_goal`. The GPT-6.1 Sol cells run through the Codex CLI, whose own wrapper prompt
and sampling cannot be set. A 20-endpoint check against the same model through the paid API
agreed on 38 of 40 item decisions.

## Pre-registration

The go/reframe rule, metrics and arm rules were committed (`d1eef3e`) before the first judge
call. The tag `prereg-v1` was due then too, but was created after the pilot; it points at the
commit every pilot call ran on (amendment of 2026-10-01). Later changes are dated amendments
and notes; the list below says where one came after the data it concerns. Deviations
from the original plan, each disclosed in [`configs/prereg.md`](../configs/prereg.md) or
[`results/phase1b/deviation-1.md`](../results/phase1b/deviation-1.md) and
[`deviation-2.md`](../results/phase1b/deviation-2.md):

- Truth moved from human labels to the state verifier after Phase 1 ran (Amendment 1).
- No infrastructure retries in Phase 1a or Phase 1b, against the stated retry policy; failed
  trials are excluded with reasons (Amendment 2).
- The first Phase 1b Stage A launch aborted: Harbor read a UTF-8 session file as cp1252 and the
  crash ended the job. It was archived, nothing from it was ingested or analysed, and Stage A
  reran from scratch with `PYTHONUTF8=1` (deviation 1).
- The timing mask in the state-pair replay rule was chosen after the replay fidelity counts were
  seen, and before any judge call on a state item (prereg note of 2026-10-14).
- The H6 test changed from a bootstrap CI rule to an exact sign-flip test before any H6 item was
  judged (same note).

## Trials and exclusions

Phase 1a has 178 decision points after two weak-arm trials timed out (88 weak, 90 strong).
Phase 1b reran the weak arm on the C2 to C4 tasks to find more failures: 520 trials, of which 19
timed out before any boundary, and 506 boundaries from the other 501, since 5 trials ran a
second turn.

21 weak-arm trials timed out on turn 1 before any boundary: 14 on `c4-04` and 7 on `c4-03` (in
Phase 1a, 2 of the 3 `c4-04` trials). They are excluded like any failed trial, per the Phase 1b
note. No strong-arm trial timed out. `c4-04` is barely observed in the weak arm.

## Phase 1b design

Phase 1b reran the weak agent on the 16 C2 to C4 tasks. Stage A ran 20 attempts per task; Stage
B ran 40 more on the 5 tasks with a not-done endpoint in Stage A. Stage B tasks were picked for
failing, so this is an enriched sample: the rates below hold within it, are never a prevalence,
and are never compared with Phase 1a.

## Second turns in Phase 1b

In Phase 1b, 5 of the 501 trials that reached a boundary ran a second turn. In 4 of them (3
`c3-05`, 1 `c4-04`) the judge said CONTINUE on a turn-1 endpoint the verifier graded done, and
DONE after turn 2, also graded done: each false CONTINUE cost one extra turn. The fifth is the
held-out `c2-03` trial, where the judge said CONTINUE on a not-done endpoint, the second turn
left it not done, and the judge said DONE.

## Phase 1b reporting rules

The 0/249 row has no events, so its bootstrap interval is degenerate and no interval is given.
Dev alone (2 tasks) and held-out alone (3 tasks) each have fewer than 5 tasks with a not-done
endpoint, so under deviation 2 they get per-task counts only, with no pooled count, rate or
interval. The other 11 tasks ran in Stage A only and have no not-done endpoint, so that pool
fails the deviation 2 rule and gets per-task counts only. On those tasks, per task, the judge
said CONTINUE on 3 of 23 done `c3-05` endpoints and 1 of 9 done `c4-04` endpoints, and on no
done endpoint of the other 9 tasks; `analysis.md` does not tabulate them. Full tables:
[`results/phase1b/analysis.md`](../results/phase1b/analysis.md).

## `repair-v1` selection

The pre-registered rule picked the iteration with the fewest false DONEs among those holding
false-CONTINUE at or under 5% on dev; iteration 3 won by one endpoint (21 of 36 against 22). The
36 are every natural design-set endpoint that is not done or blocked: 24 not done (1 Phase 1a
strong `c2-01`, 16 Phase 1b `c2-01` and 7 Phase 1b `c2-05`) and 12 blocked Phase 1a dev
endpoints. It is a design-set selection figure under Amendment 3, not a reported rate. The
iterations are in [`results/repair/`](../results/repair/).

## Controlled pairs

State pairs cover the 35 of 70 dev endpoints whose last three calls replay under the timing
mask, pinned at `826ca9b`, which favours simple endings. Replay is checked on stored
500-character output tails, not full output. A confirmatory pairs run would need held-out
endpoints and its own amendment.

## Reliability

Hermes falls back to CONTINUE when it cannot parse a verdict, which would hide false DONEs if
parsing failed often. Across 3,204 Phase 2 judge calls there were 2 parse failures, both on the
weak self judge, and no format violations. The Codex CLI cells needed many retries. Timed-out
attempts: `prod-plain:strong` 139/403 (34.5%) weak and 120/390 (30.8%) strong;
`repair-v1:strong:evidence` 16/280 (5.7%) weak and 15/285 (5.3%) strong; 155 in `phase2-weak`
and 135 in `phase2-strong`. Every call finished.

## The pilot

Before building tasks, 48 constructed items checked that the effects existed at all
([`results/runs/pilot-v1/summary.md`](../results/runs/pilot-v1/summary.md)). Every judge model
accepted every confident false claim (4 of 4 each). A caveat at about 1,000 characters was
mostly caught; the same caveat at 4,500 or 8,000 characters was mostly missed. Keeping the first
and last 2,000 characters recovered the 8,000-character caveat but lost one at 3,500, which then
fell in the cut middle. The pilot's self judge was Qwen3-Coder, which was later replaced as the
weak agent after failing the soak gate.

## Cost

Paid judge calls cost $7.18 against the pre-registered $20 stop
([`results/runs/phase2/spend.md`](../results/runs/phase2/spend.md)): the Phase 2 replay $1.78,
its paid-API sanity check $0.22, the `probe-p2` format probes $0.02, the three `repair-v1` design
iterations $3.44 and the controlled pairs $1.72. The 1,315 GPT-6.1 Sol calls ran on a
subscription and are not billed per call.

Phase 1b ran on a dedicated key with its own $20 cap, covering agent, auxiliary and in-loop
judge calls ([Stage A](../results/phase1b/stage-a-report.md) and
[Stage B](../results/phase1b/stage-b-report.md) reports):

| Phase 1b spend | USD |
|---|---|
| Aborted first Stage A launch | 0.038047 |
| Stage A, measured at its end | 2.557706 |
| Billed between the Stage A end reading and the Stage B baseline | 0.010487 |
| Stage B | 1.930782 |
| **Total** | **4.537022 (about $4.54)** |

The $0.010487 is not attributed to any recorded call. The Stage B report counts it as late
Stage A billing, because no other job ran on the key, and revises Stage A to $2.568193. The pilot
cost $1.65. No billed agent spend for Phase 1a or the soak runs is in the repository.

## Reproducing

```bash
git clone --recurse-submodules https://github.com/blueuwu/hermes-judge-audit.git
cd hermes-judge-audit
uv sync
uv run pytest
uv run hjr phase2-summary              # results/runs/phase2/summary.md
uv run hjr phase2-summary --truth v1   # summary-v1.md, unfixed verifier
```

The pairs summaries are rebuilt with the command in
[`results/runs/pairs/README.md`](../results/runs/pairs/README.md). None of these make model
calls. Rerunning trajectories needs Docker, Harbor and the raw job directories, which are not in
the repository.
