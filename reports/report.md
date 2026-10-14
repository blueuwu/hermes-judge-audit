# Does the Hermes `/goal` judge know when a goal is done?

October 2026. Code: this repository. Pre-registration: [`configs/prereg.md`](../configs/prereg.md).

Hermes Agent's `/goal` command runs the agent in a loop until a judge model decides the goal is
met. After each turn the judge reads the goal and the agent's final message and answers DONE,
CONTINUE or BLOCKED. At the audited commit
([`ffc74885`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py))
the judge sees the goal, cut to 2,000 characters, and the first 4,000 characters of that final
message. It sees no tool output and no workspace, and by default it is the agent's own model.

That input sets a bound. When the agent says it is done and is wrong, nothing the judge sees
says otherwise, so no judge model can tell, and changing the model cannot help. This study
measures what that bound costs on real tasks, then asks what the judge does when the evidence
is in its input.

## Summary

- **The bound holds: the judge accepted every unfinished task the agent called finished.** Of
  178 trajectory endpoints from two agents, 9 were not done by the verifier: 4 weak, 5 strong.
  Every production-prompt cell, with the agent's own model, Gemini 3 Flash Preview or GPT-6.1
  Sol as judge, judged all 9 DONE. Wilson 95% intervals: 4/4 weak, 51.0 to 100%; 5/5 strong,
  56.6 to 100%; 9/9 across both arms, descriptive only, 70.1 to 100%. The 23 not-done endpoints
  from the Phase 1b enrichment runs were all judged DONE by the in-loop judge too.
- **The same input explains what it gets right.** A blocked agent says so, and the judge judged
  none of the 12 blocked endpoints per arm DONE. Under the agent's own model it held back none
  of the finished ones. The design claim that false-DONE is rarer than false-CONTINUE (H1) is
  reversed in both arms, although with so few failing tasks the intervals reach 0.
- **Past the bound, the production prompt still calls visible breakage DONE.** On constructed
  pairs where a required file was broken and the replayed tool output in the judge's input
  showed it, the production prompt called the broken copy DONE in 7 of 7 (weak) and 2 of 2
  (strong) pairs. On natural endpoints, adding tool output removed no false DONE.
- **A prompt that tells the judge to check (`repair-v1`) helps a little, at a cost.** It caught 3
  of 7 and 1 of 2 of those broken copies, and 1 natural not-done endpoint in the strong arm. It
  held back up to 5 finished tasks per arm. The pre-registered repair test (H4) is not met,
  which the power analysis predicted before any call was made.
- **Truncation keeps the start of long messages, where the docs say the end.** No natural final
  message here was longer than 2,757 characters, so these agents never reached the cut. On
  controlled pairs a caveat before the cut changed 2 (weak) and 4 (strong) decisions and after
  the cut none, but the changes sit in two tasks per arm, too few for the pre-registered test
  (H6).

The short version: in its production form the judge grades the agent's report. When the report
says done, the judge agrees, and with tool output added it still agrees when that output shows
the work is broken.

## Setup

### Tasks and agents

30 tasks in six categories, run in Harbor sandboxes under the real `/goal` loop
([`tasks/README.md`](../tasks/README.md)):

| Category | Tasks | What it tests |
|---|---|---|
| C1 controls | 5 | Plain tasks the agent should finish |
| C2 multi-part | 5 | Goals with several requirements, one of which is easy to skip |
| C3 tool friction | 6 | Missing interpreters, flaky syncs, stale locks |
| C4 verification-required | 5 | Adapted from Terminal-Bench 2.0; the agent sees little or none of the checking |
| C5 infeasible | 4 | Goals that cannot be met without something the agent lacks |
| C6 long reports | 5 | Tasks whose answer is a long written report |

A seeded split puts 12 tasks in dev and 18 in held-out. The repair prompt was built from dev
only and frozen (tag `repair-freeze-v1`) before any held-out endpoint was read.

Two agent arms, from different vendors on different providers: weak is GLM-5.3-Flash on Z.AI,
strong is DeepSeek V4.1 Flash on DeepSeek. Each ran every task 3 times with a six-turn budget.
Every trial ended after its first turn: the agent worked, wrote a summary, and the in-loop judge
stopped it. That gives one decision point per trial, 178 in all after two weak-arm trials timed
out (88 weak, 90 strong). This is Phase 1a. Phase 1b reran the weak arm on the C2 to C4 tasks
to find more failures (506 more endpoints); it is an enriched sample and never enters a rate.

### Truth

Each task has a hidden, per-requirement state verifier that runs without network in its own
container and grades the workspace at the decision point. Truth is `done`, `not_done` or
`blocked`; C5 tasks are `blocked` whatever the agent does.

The verifier was tested before it was trusted. A mutation suite broke each requirement of each
task's reference solution in turn: 260 of 260 mutants were caught on the requirement they
targeted, and 33 of 33 benign variants passed. Two verifier defects found while reading failing
dev endpoints were fixed before the freeze. One `c2-01` check rejected reasonable work (adding a
test, documenting the alias the goal asked for), and one `c6-04` check expected a rule name the
task never gave. Fixing them moved 7 dev endpoints from not done to done. Every table is also
produced with the unfixed verifier as a sensitivity check.

After the judge runs, a blind human audit checked 49 endpoints against the verifier, drawn in
three strata of verifier/judge agreement. The auditor saw neither the judge verdict nor the
stratum.

| Stratum | Population | Audited | Verifier errors | Wilson 95% |
|---|---:|---:|---:|---|
| Verifier and judge disagree | 9 | 9 | 0 | 0 to 29.9% |
| Both say DONE | 145 | 30 | 0 | 0 to 11.4% |
| Both say not DONE | 24 | 10 | 1 | 1.8 to 40.4% |

The one error is a `c5-03` endpoint where the agent's tests passed in its own environment but
the verifier's image lacked the agent's installed packages. The endpoint is still correctly
`blocked`, so no truth label changes. The "both say DONE" row matters most here: it is where a requirement the
verifier never checked would hide a false DONE, and 0 of 30 bounds that at about 11%.

### Judge cells

Each Phase 1a endpoint was replayed offline through six judge cells, 3 samples each. The item
decision is the majority of 3.

| Cell | Prompt | Judge | Input |
|---|---|---|---|
| `prod-plain:self:head4k` | production | the agent's own model | production: goal and first 4,000 characters |
| `prod-plain:flash:head4k` | production | Gemini 3 Flash Preview, the judge override in Hermes's docs | production |
| `prod-plain:strong:head4k` | production | GPT-6.1 Sol via Codex CLI | production |
| `prod-plain:flash:evidence` | production | Gemini 3 Flash Preview | head and tail of the message, plus the last 3 tool calls with exit codes and output tails |
| `repair-v1:flash:evidence` | `repair-v1` | Gemini 3 Flash Preview | evidence |
| `repair-v1:strong:evidence` | `repair-v1` | GPT-6.1 Sol via Codex CLI | evidence |

Production cells reproduce what Hermes sends byte for byte; a test checks every replayed prompt
against `judge_goal`. The GPT-6.1 Sol cells run through the Codex CLI, whose own wrapper prompt
and sampling cannot be set. A 20-endpoint check against the same model through the paid API
agreed on 38 of 40 item decisions.

### Pre-registration

Hypotheses, metrics, tests and stopping rules were tagged (`prereg-v1`) before the first judge
call. Every later change is a dated amendment committed before the work it governs. Two
deviations are disclosed: the switch from human labels to verifier truth was made after Phase 1
ran, and Phase 1a ran with no infrastructure retries (Amendment 2).

## Results

All numbers are per agent arm. The two arms are never pooled.

### Natural trajectories

Errors by truth class: `not_done` and `blocked` endpoints judged DONE (false DONE), and `done`
endpoints judged anything else (false CONTINUE).

| Cell | weak: not_done → DONE | weak: blocked → DONE | weak: false CONTINUE | strong: not_done → DONE | strong: blocked → DONE | strong: false CONTINUE |
|---|---|---|---|---|---|---|
| `prod-plain:self:head4k` | 4/4 | 0/12 | 0/72 | 5/5 | 0/12 | 0/73 |
| `prod-plain:flash:head4k` | 4/4 | 0/12 | 0/72 | 5/5 | 0/12 | 0/73 |
| `prod-plain:strong:head4k` | 4/4 | 0/12 | 1/72 | 5/5 | 0/12 | 2/73 |
| `prod-plain:flash:evidence` | 4/4 | 0/12 | 0/72 | 5/5 | 0/12 | 0/73 |
| `repair-v1:flash:evidence` | 4/4 | 0/12 | 0/72 | 4/5 | 0/12 | 2/73 |
| `repair-v1:strong:evidence` | 4/4 | 0/12 | 5/72 | 4/5 | 0/12 | 5/73 |

The pre-registered false-DONE rate combines the two DONE columns per arm (4/16 weak, 5/17
strong under production cells), which hides that every error is `not_done`. The Summary's Wilson
intervals treat endpoints as independent; three of each arm's not-done endpoints are trials of
one task (`c6-02`), so the real uncertainty is wider.

Accuracy looks good and says little. The production self judge is right on 95.0% (weak) and
94.4% (strong) of parsed calls, and Cohen's κ is 0.83 and 0.80 (PABAK 0.91 and 0.89). But 72 of
88 and 73 of 90 endpoints are done, and blocked endpoints are easy, because a blocked agent says
so. With this input the judge can only be right when the agent's account is right. The agent's
own completion claim was not labelled per endpoint, so this study has no table of claim against
truth to show that link directly.

- **H1 (false-DONE below false-CONTINUE): reversed.** The docs state this as the prompt's aim
  ([`goals.md:291`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L291)). FD minus FC under the production self
  judge is +25.0 points (weak, task-bootstrap 95% interval 0.0 to 68.4) and +29.4 points (strong,
  0.0 to 70.0). The prediction was a negative difference. The intervals reach 0 because the
  failures come from a handful of tasks. With the unfixed verifier the strong arm's interval
  excludes 0 (+42.9 points, 6.2 to 80.0).
- **H2 (where false DONE happens): descriptive.** Every false DONE is on a C2, C4 or C6 task. C1
  and C3 produced no not-done endpoints, so there is no comparison against controls.
- **H3 (completion-contract prompt): not tested.** Phase 1 ran only the plain `/goal` path.
- **H5 (an independent judge is more accurate): no, as the input predicts.** Every model sees
  the same goal and message, and none can recover a failure the message leaves out. Item
  correctness of the self judge, Flash and GPT-6.1 Sol differs by at most 2 endpoints out of 88
  or 90. Flash matches the self judge exactly in both arms. GPT-6.1 Sol makes the same
  false-DONE decisions and adds 1 (weak) and 2 (strong) false CONTINUEs.

The Phase 1b dev pools tell the same story at a larger size. The in-loop judge (GLM-5.3-Flash,
production prompt) judged 16 of 16 not-done `c2-01` endpoints and 7 of 7 not-done `c2-05`
endpoints DONE. These come from two tasks, so they are counts, not a rate.

### Where the judge fails

The misses fall into two zones, set by whether the failure reaches the judge's input. (This is
separate from judge-model drift, which the prereg and `hjr/drift.py` use for verdict changes
between versions of the judge model.)

**Information-limited: the failure never appears in what the judge sees.**

- `c2-01`: the unmet requirement is where a name sits in `docs/API.md`. The `repair-v1` design
  set has 17 not-done `c2-01` endpoints: 1 from Phase 1a strong and 16 from Phase 1b weak. They
  were classified before iteration 2 as not showing the problem in the last three tool calls.
  `repair-v1:flash:evidence` called 16 of 17 DONE (Phase 1a strong 1 of 1, Phase 1b weak 15 of
  16). The one it caught is an endpoint whose last command did grep `docs/API.md`.
- H8 pairs: 8 weak and 6 strong state pairs (Phase 1a dev) were dropped because the breakage
  did not reach the tool output the judge sees.

No prompt can fix this zone. The judge needs a different input.

**Attention-limited: the failure is visible and still missed.**

- H8 pairs: `prod-plain:flash:evidence` judged 0 of 7 (weak) and 0 of 2 (strong) visibly broken
  copies not DONE.
- `c2-05`: the unmet requirement is the order or contents of a manifest, which tool output
  displays. The design set has 7 not-done `c2-05` endpoints, all from Phase 1b weak.
  `repair-v1:flash:evidence`, the prompt that tells the judge to check, called 5 of 7 DONE. In
  one, the goal asked for the manifest sorted by filename, and the `sha256sum -c` output in the
  judge's input listed `2026-09-24.csv` first and `2026-09-03.csv` last. All three samples gave
  the same reason:

  > created the MANIFEST.txt file with correct checksums and sorting.

The 23 Phase 1b endpoints here were judged only by the in-loop judge and, during its design, by
`repair-v1:flash:evidence`; the Phase 1a one also went through every Phase 2 cell. All are
per-task counts.

### The repair (H4)

`repair-v1` puts general checking instructions before the item and uses the evidence view. It
was designed in three iterations on dev data only. The pre-registered rule picked the iteration
with the fewest false DONEs among those holding false-CONTINUE at or under 5% on dev; iteration 3
won by one endpoint (21 of 36 against 22). Its prompt changes cut down on the judge over-reading
evidence on finished tasks; every iteration still called 5 of the 7 visible `c2-05` failures
DONE.

H4 asks for false-DONE on held-out endpoints to fall by at least 10 points, with at least 15
discordant pairs, while false-CONTINUE rises by at most 5 points. With 10 held-out not-done or
blocked endpoints per arm, 15 discordant pairs were never reachable, as the power note said.

| Held-out, against the same model's `prod-plain:<m>:head4k` | weak | strong |
|---|---|---|
| False-DONE, `repair-v1:flash:evidence` | no change (0 discordant) | −10 points (1 discordant) |
| False-DONE, `repair-v1:strong:evidence` | no change (0 discordant) | −10 points (1 discordant) |
| False-CONTINUE, `repair-v1:flash:evidence`, 44 done | no change | +2.3 points |
| False-CONTINUE, `repair-v1:strong:evidence`, 44 done | +6.8 points | +4.5 points |

H4 is not met in any of its four tests (Holm-adjusted p = 1 in each). The repair caught one
natural endpoint and held back up to three finished ones on held-out data. Across all endpoints
`repair-v1:strong:evidence` held back 5 finished tasks per arm, the most of any cell.

### Controlled pairs

Natural data had too few failures and no long messages, so the last stage built pairs on dev
endpoints: two inputs that differ in one thing, judged 3 times each. A noise check
judged every base twice on identical input: 0 of 34 (weak) and 0 of 36 (strong) decisions
changed.

| `prod-plain:flash` unless noted | weak | strong |
|---|---|---|
| Caveat before the 4,000-character cut: decisions changed | 2/34 | 4/36 |
| Same caveat after the cut: decisions changed | 0/34 | 0/36 |
| Hedged, error-mentioning, paraphrased or casual rewrite: decisions changed, each family | 0/12 | 0/12 |
| Broken required file visible in tool output, judged not DONE: `prod-plain:flash:evidence` | 0/7 | 0/2 |
| same, `repair-v1:flash:evidence` | 3/7 | 1/2 |
| same, `repair-v1:strong:evidence` | 3/7 | 1/2 |

- **H6 (truncation): not established.** The direction is the one the pilot showed, and no
  caveat after the cut changed anything. But the changed decisions come from 2 tasks per arm,
  and the pre-registered exact test needs at least 5 tasks with a difference. p = 0.25 in both
  arms.
- **E1 (meaning-preserving rewrites): descriptive.** Paraphrased and casual rewrites changed no
  decision. With 12 bases the exact 95% upper bound on the change rate is 26.5%, so no rewrite
  family is called inert.
- **Hedging and error mentions.** 10 of 12 bases per arm were judged DONE before the edit and
  stayed DONE after it, including after a paragraph saying a command exited with an error.
- **H8 (does the evidence view see broken state): descriptive.** With 7 and 2 pairs no test can
  reach significance (smallest p 0.25 weak, 1.0 strong; 1.0 after Holm).
- **H7 (adding a confident claim): not run.** It needs a not-done dev endpoint whose message
  claims nothing, and there is none.

These pairs are a pilot on 12 dev tasks per arm. They show which way the judge leans; they are
not estimates.

### Reliability

Hermes falls back to CONTINUE when it cannot parse a verdict, which would hide false DONEs if
parsing failed often. Across 3,204 Phase 2 judge calls there were 2 parse failures, both on the
weak self judge, and no format violations. The Codex CLI hangs on 10 to 30% of attempts, so its
cells needed many retries (139 and 120 timed-out attempts in the two `prod-plain:strong` runs),
but every call finished.

### The pilot

Before building tasks, 48 constructed items checked that the effects existed at all
([`results/runs/pilot-v1/summary.md`](../results/runs/pilot-v1/summary.md)). Every judge model
accepted every confident false claim (4 of 4 each). A caveat at about 1,000 characters was
mostly caught; the same caveat at 4,500 or 8,000 characters was mostly missed. Keeping the first
and last 2,000 characters recovered the 8,000-character caveat but lost one at 3,500, which then
fell in the cut middle. The pilot's self judge was Qwen3-Coder, which was later replaced as the
weak agent after failing the soak gate.

## What this means for Hermes

These results are about the judge as shipped at `ffc74885`, on these tasks and agents.

- **Treat the judge as a check on the agent's report.** It stops a loop when the agent says it
  is done and pauses one when the agent says it is stuck. The docs describe this design: the
  judge marks a goal done only when the response explicitly confirms it
  ([`goals.md:188`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L188)). When the agent is wrong about its own work, the judge has
  nothing to go on.
- **A stronger judge model will not fix this.** Three models from three vendors made the same
  false-DONE decisions, which is what the input predicts.
- **Passing the last few tool outputs is not enough by itself.** In the information-limited
  zone the failure is not in them. In the attention-limited zone the production prompt ignored
  it. A prompt that asks the judge to check caught some and cost some finished tasks.
- **Fix the truncation mismatch.** The docs
  ([`goals.md:185`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L185))
  say the judge reads the "last ~4 KB of text". The code
  ([`goals.py:928`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py#L928))
  passes `_truncate(last_response, _JUDGE_RESPONSE_SNIPPET_CHARS)`, where the constant is 4000
  (line 39) and `_truncate` keeps `text[:limit]` (line 713), the first 4,000 characters. Either
  the docs should say "first ~4 KB" or the code should keep the tail. The pilot suggests head
  plus tail is not enough on its own. These agents never wrote a message long enough to hit it.
- **Check state (untested).** A fix for the information-limited zone needs the judge, or the
  loop, to look at state: run the task's own checks, or ask the agent for evidence it can
  only produce by doing the work. Hermes already has a mechanism of this kind: quality gates
  ([`goals.md:135`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L135)),
  shell commands that must pass before the judge is called. No trial here configured a gate,
  so this study measured the judge alone and did not test gates or any other state check.

## Limitations

- **One turn per trial.** Every trial ended after turn 1, so the loop never iterated. A false
  CONTINUE was never acted on, so its real cost (the extra turns it causes) was not measured.
- **Few failures.** The natural not-done endpoints number 4 and 5 per arm, from 2 tasks (weak)
  and 3 tasks (strong). The Phase 1b failures come from two dev tasks. Every rate here comes
  with that caveat, and most are reported as counts.
- **Short messages.** No natural final message reached 4,000 characters, so truncation is
  measured only on constructed inputs.
- **The verifier is the truth.** It passed the mutation suite and the audit found 1 error in 49,
  but a requirement the spec never states would not be checked. The audit had one auditor.
- **GPT-6.1 Sol runs through the Codex CLI.** Its cells differ from the Flash cells in harness as
  well as model. The 20-endpoint check against the paid API bounds that, not more.
- **The pairs are a dev pilot.** State pairs cover only endpoints whose last three commands
  replay exactly, which favours simple endings. Replay is checked on stored 500-character output
  tails, not full output. A confirmatory pairs run would need held-out endpoints and its own
  amendment.

## Cost

Paid judge calls in Phase 2, the repair design and the pairs cost $7.18 against a pre-registered
$20 stop ([`results/runs/phase2/spend.md`](../results/runs/phase2/spend.md)). The pilot cost
$1.65. The 1,315 GPT-6.1 Sol calls ran on a subscription and are not billed per call.

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
