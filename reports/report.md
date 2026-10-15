# Does the Hermes `/goal` judge know when a goal is done?

October 2026. Code: this repository. Pre-registration: [`configs/prereg.md`](../configs/prereg.md).
Methods, deviations, exclusions and spend: [`docs/methods.md`](../docs/methods.md).

Hermes Agent's `/goal` command runs the agent in a loop until a judge model decides the goal is
met. After each turn the judge reads the goal and the agent's final message and answers DONE,
CONTINUE or BLOCKED. At the audited commit
([`ffc74885`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py))
the judge sees the goal, cut to 2,000 characters, and the first 4,000 characters of that final
message. It sees no tool output and no workspace, and by default it is the agent's own model.

That input sets a bound. When the agent says it is done and is wrong, nothing the judge sees
says otherwise, so from that input no judge model can tell a true done claim from a false one,
and changing the model cannot help. This study measures what that bound costs on real tasks,
then asks what the judge does when the evidence is in its input.

The short version: in its production form the judge grades the agent's report. When the report
says done, the judge agrees, and with tool output added it still agrees when that output shows
the work is broken.

## Summary

- **Past the bound, the production prompt still calls visible breakage DONE.** On constructed
  dev pairs where a required file was broken and the replayed tool output in the judge's input
  showed it, the production prompt called the broken copy DONE in 7 of 7 (weak) and 2 of 2
  (strong) pairs. These pairs are a pilot. On natural endpoints, adding tool output removed no
  false DONE.
- **Truncation keeps the start of long messages, where the docs say the end.** The code passes
  the first 4,000 characters; the docs say the "last ~4 KB of text". No natural final message
  here was longer than 2,757 characters, so these agents never reached the cut, and truncation
  is measured only on constructed inputs.
- **In Phase 1a the bound holds: the judge accepted every unfinished task the agent called
  finished.**
  - Of 178 trajectory endpoints from two agents, 9 were not done by the verifier. Every
    production-prompt cell (the agent's own model, Gemini 3 Flash Preview, GPT-6.1 Sol) judged
    all 9 DONE: 4/4 weak and 5/5 strong, counts only, since cells under 20 items report no
    rates. All 9 final messages open by reporting the work done (appendix).
  - Phase 1b (weak arm only, an enriched sample): the in-loop judge judged 44 of 45 not-done
    endpoints DONE, across 5 tasks (per task: dev `c2-01` 16/16 and `c2-05` 7/7; held-out
    `c2-03` 3/4, `c4-03` 16/16 and `c4-05` 2/2). The exception, judged CONTINUE, is
    described under Results.
  - The same input explains what it gets right: a blocked agent says so, and the judge judged
    none of the 12 blocked endpoints per arm DONE; under the agent's own model it held back none
    of the finished ones.
- **A prompt that tells the judge to check (`repair-v1`) helps a little, at a cost.** It caught 3
  of 7 and 1 of 2 of those broken copies, and 1 natural not-done endpoint in the strong arm. It
  held back up to 5 finished tasks per arm.
- **Pre-registered tests.** H1 (false-DONE rarer than false-CONTINUE): the point estimate is reversed in both
  arms, although with so few failing tasks the intervals reach 0. H4 (the repair test): not met,
  which the power analysis predicted before any call was made. H6 (truncation): not
  established; a caveat before the cut changed 2 (weak) and 4 (strong) decisions and after the
  cut none, but the changes sit in two tasks per arm, too few for the pre-registered test.

## What I built

- 30 tasks in six categories, run in Harbor sandboxes under the real `/goal` loop, with two
  agent arms from different vendors ([`tasks/README.md`](../tasks/README.md)).
- A hidden, per-requirement state verifier for every task. A mutation suite: 260 of 260 mutants
  caught on the requirement they targeted, 33 of 33 benign variants passed. A blind human audit
  of 49 endpoints.
- An offline replay of 3,204 judge calls through six judge cells, with judge models from 3
  vendors in each arm. Production cells reproduce what Hermes sends byte for byte, checked by a
  test against `judge_goal`.
- Controlled pairs built from stored trajectories: two inputs that differ in one thing, including
  state pairs where a required file was broken and the endpoint's last three tool calls were
  replayed against it.
- On the way, a Harbor bug: it read a UTF-8 session file as cp1252, which ended the first Phase
  1b launch ([`results/phase1b/deviation-1.md`](../results/phase1b/deviation-1.md)).

## Setup

### Tasks and agents

30 tasks in six categories: C1 controls, C2 multi-part, C3 tool friction, C4
verification-required, C5 infeasible and C6 long reports
([table](../docs/methods.md#tasks), [`tasks/README.md`](../tasks/README.md)).

A seeded split puts 12 tasks in dev and 18 in held-out. The repair prompt was built from dev
only and frozen (tag `repair-freeze-v1`) before any held-out endpoint was read.

Two agent arms, from different vendors on different providers: weak is GLM-5.3-Flash on Z.AI,
strong is DeepSeek V4.1 Flash on DeepSeek. Each ran every task 3 times with a six-turn budget.
Every Phase 1a trial ended after its first turn: the agent worked, wrote a summary, and the
in-loop judge stopped it. That gives one decision point per trial, 178 in all (88 weak, 90
strong). This is Phase 1a. Phase 1b reran the weak arm on the C2 to C4 tasks to find more
failures, for 506 boundaries. It is an enriched sample, reported on its own and never as a
prevalence. Exclusions are in [methods](../docs/methods.md#trials-and-exclusions).

### Truth

Each task has a hidden, per-requirement state verifier that runs without network in its own
container and grades the workspace at the decision point. Truth is `done`, `not_done` or
`blocked`; C5 tasks are `blocked` whatever the agent does.

The verifier was tested before it was trusted, with the mutation suite above. Two defects found
on dev were fixed before the freeze, and every table is also produced with the unfixed verifier
as a sensitivity check ([methods](../docs/methods.md#verifier)).

After the judge runs, a blind human audit checked 49 endpoints against the verifier, drawn in
three strata of verifier/judge agreement. The auditor saw neither the judge verdict nor the
stratum.

| Stratum | Population | Audited | Endpoint label errors | Wilson 95% |
|---|---:|---:|---:|---|
| Verifier and judge disagree | 9 | 9 | 0 | 0 to 29.9% |
| Both say DONE | 145 | 30 | 0 | 0 to 11.4% |
| Both say not DONE | 24 | 10 | 0 | 0 to 27.8% |

The auditor found one requirement-level error, in a weak-arm `c5-03` endpoint; its label,
`blocked`, is unchanged and still correct. Counted as the prereg's verifier error rate, which
includes requirement-level errors, stratum C has 1 of 10 (Wilson 1.8 to 40.4%,
[methods](../docs/methods.md#verifier-audit-the-requirement-level-error)). The "both say DONE"
row matters most here: it is where a requirement the verifier never checked would hide a false
DONE, and 0 of 30 bounds that at about 11%.

### Judge cells

Each Phase 1a endpoint was replayed offline through six judge cells, 3 samples each. The item
decision is the majority of 3. How the cells were run is in
[methods](../docs/methods.md#judge-cells).

| Cell | Prompt | Judge | Input |
|---|---|---|---|
| `prod-plain:self:head4k` | production | the agent's own model | production: goal and first 4,000 characters |
| `prod-plain:flash:head4k` | production | Gemini 3 Flash Preview, the judge override in Hermes's docs | production |
| `prod-plain:strong:head4k` | production | GPT-6.1 Sol via Codex CLI | production |
| `prod-plain:flash:evidence` | production | Gemini 3 Flash Preview | head and tail of the message, plus the last 3 tool calls with exit codes and output tails |
| `repair-v1:flash:evidence` | `repair-v1` | Gemini 3 Flash Preview | evidence |
| `repair-v1:strong:evidence` | `repair-v1` | GPT-6.1 Sol via Codex CLI | evidence |

The go/reframe rule, metrics and arm rules were committed (`d1eef3e`) before the first judge
call. Amendments and every deviation are listed in
[methods](../docs/methods.md#pre-registration).

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
strong under production cells), which hides that every error is `not_done`. The not-done
endpoints come from 2 tasks (weak) and 3 tasks (strong), and three of each arm's are trials of
one task (`c6-02`), so the endpoints are not independent.

Accuracy looks good and says little. The production self judge is right on 95.0% (weak) and
94.4% (strong) of parsed calls, and Cohen's κ is 0.83 and 0.80 (PABAK 0.91 and 0.89). But 72 of
88 and 73 of 90 endpoints are done, and blocked endpoints are easy, because a blocked agent says
so. With this input the judge has only the agent's account to go on. Completion
claims were not labelled across all 178 endpoints, so there is no table of claim against truth,
but the appendix shows the claims for the 9 not-done ones.

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

### Phase 1b enrichment (weak arm)

Stage B tasks were picked for failing, so this is an enriched sample: the rates below hold
within it, are never a prevalence, and are never compared with Phase 1a
([design](../docs/methods.md#phase-1b-design)). Stage A alone, the uniform part, found 19 not-done
endpoints in 310. The judge here is the in-loop one (GLM-5.3-Flash, production prompt). Full
tables: [`results/phase1b/analysis.md`](../results/phase1b/analysis.md).

On the 5 selected tasks (Stage A and B, 294 endpoints):

| In-loop judge | Count | Micro (task bootstrap 95%) | Task-macro (task bootstrap 95%) |
|---|---|---|---|
| DONE on not-done endpoints | 44/45 | 97.8% (89.5 to 100) | 95.0% (85.0 to 100) |
| Not DONE on done endpoints, 5 selected tasks only | 0/249 | 0% | 0% |

| Task | Split | Not done judged DONE |
|---|---|---|
| `c2-01-rename-function` | dev | 16/16 |
| `c2-05-month-end-close` | dev | 7/7 |
| `c2-03-release-bump` | held-out | 3/4 |
| `c4-03-cobol-modernization` | held-out | 16/16 |
| `c4-05-log-summary-date-ranges` | held-out | 2/2 |

- The intervals are coarse: the bootstrap resamples 5 task clusters, all 5 with a not-done
  endpoint judged DONE. Dev alone, held-out alone and the other 11 tasks get per-task counts
  only, under deviation 2 ([methods](../docs/methods.md#phase-1b-reporting-rules)).
- The one not-done endpoint not judged DONE is the first of two in a held-out `c2-03` trial. Its
  final message opened "Release done." and closed by offering to bump one more version string.
  The judge said CONTINUE, and on the second endpoint, still not done, it said DONE. The first
  final message is quoted in the appendix.

### Where the judge fails

The misses fall into two zones, set by whether the failure reaches the judge's input.

**Information-limited: the failure never appears in what the judge sees.**

- `c2-01`: the unmet requirement is where a name sits in `docs/API.md`. The `repair-v1` design
  set has 17 not-done `c2-01` endpoints: 1 from Phase 1a strong and 16 from Phase 1b weak. They
  were classified before iteration 2 as not showing the problem in the last three tool calls.
  `repair-v1:flash:evidence` called 16 of 17 DONE (Phase 1a strong 1 of 1, Phase 1b weak 15 of
  16). The one it caught is an endpoint whose last command did grep `docs/API.md`. That catch
  was right for the wrong reason: its CONTINUE reasons read the old-name header in
  `docs/API.md` as a use left un-updated, the over-reading the iteration meant to remove, so the
  blind spot stands ([`results/repair/iteration-3.md`](../results/repair/iteration-3.md)).
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
was designed in three iterations on dev data only, and the pre-registered rule picked iteration 3
([methods](../docs/methods.md#repair-v1-selection)). Its prompt changes cut down on the judge
over-reading evidence on finished tasks; every iteration still called 5 of the 7 visible `c2-05`
failures DONE.

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

- **H6 (truncation): not established.** The direction is the one the
  [pilot](../docs/methods.md#the-pilot) showed, and no caveat after the cut changed anything.
  But the changed decisions come from 2 tasks per arm, and the pre-registered exact test needs
  at least 5 tasks with a difference. p = 0.25 in both arms.
- **E1 (meaning-preserving rewrites): descriptive.** Paraphrased and casual rewrites changed no
  decision. With 12 bases the exact 95% upper bound on the change rate is 26.5%, so no rewrite
  family is called inert.
- **Hedging and error mentions.** 10 of 12 bases per arm were judged DONE before the edit and
  stayed DONE after it, including after a paragraph saying a command exited with an error.
- **H8 (does the evidence view see broken state): descriptive.** With 7 and 2 pairs no test can
  reach significance (smallest p 0.25 weak, 1.0 strong; 1.0 after Holm).
- **H7 (adding a confident claim): not run.** It needs a not-done dev endpoint whose message
  claims nothing, and there is none.

Apart from H6, which is confirmatory on dev, these pairs are a pilot on 12 dev tasks per arm.
They show which way the judge leans; they are not estimates. State pair coverage, which favours
simple endings, is in [methods](../docs/methods.md#controlled-pairs).

## What this means for Hermes

These results are about the judge as shipped at `ffc74885`, on these tasks and agents.

- **Treat the judge as a check on the agent's report.** It stops a loop when the agent says it
  is done and pauses one when it says it is stuck, as the docs describe: done only when the
  response explicitly confirms it
  ([`goals.md:188`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L188)). When the agent is wrong about its own work, the judge has
  nothing to go on.
- **A stronger judge model will not fix this.** Three models from three vendors made the same
  false-DONE decisions, which is what the input predicts.
- **Passing the last few tool outputs is not enough by itself.** In the information-limited
  zone the failure is not in them; in the attention-limited zone the production prompt ignored
  it, and a prompt that asks the judge to check caught some and cost some finished tasks.
- **Fix the truncation mismatch.** The docs
  ([`goals.md:185`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L185))
  say the judge reads the "last ~4 KB of text". The code
  ([`goals.py:928`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py#L928))
  passes `_truncate(last_response, _JUDGE_RESPONSE_SNIPPET_CHARS)`, where the constant is 4000
  (line 39) and `_truncate` keeps `text[:limit]` (line 713), the first 4,000 characters. Either
  the docs should say "first ~4 KB" or the code should keep the tail. The pilot suggests head
  plus tail is not enough on its own. These agents never wrote a message long enough to hit it.
  The head-only cut was reported upstream before this study, in
  [issue #70699](https://github.com/NousResearch/hermes-agent/issues/70699) and
  [PR #70701](https://github.com/NousResearch/hermes-agent/pull/70701), both opened on
  2026-07-24 and open at the time of writing.
- **Check state (untested).** A fix for the information-limited zone needs the judge, or the
  loop, to look at state: run the task's own checks, or ask the agent for evidence it can
  only produce by doing the work. Hermes has quality gates
  ([`goals.md:135`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L135)),
  shell commands that must pass before the judge is called. No trial here configured a gate,
  so this study measured the judge alone and did not test gates or any other state check.

## Limitations

- **One turn per trial in Phase 1a.** The loop never iterated there, and a false CONTINUE was
  never acted on. In Phase 1b, 4 false CONTINUEs on done endpoints each cost one
  extra turn, and the fifth second turn is the `c2-03` trial above
  ([methods](../docs/methods.md#second-turns-in-phase-1b)). Five trials do not measure the cost of false
  CONTINUEs in general.
- **`c4-04` is barely observed in the weak arm.** 14 of the 21 weak-arm trials that timed out
  before any boundary were on it ([methods](../docs/methods.md#trials-and-exclusions)).
- **The verifier is the truth.** It passed the mutation suite, and the audit of 49 endpoints
  found no endpoint label error and one requirement-level error, but a requirement the spec
  never states would not be checked. The audit had one auditor.
- **GPT-6.1 Sol runs through the Codex CLI.** Its cells differ from the Flash cells in harness as
  well as model. The 20-endpoint check against the paid API, which agreed on 38 of 40 item
  decisions, bounds that, not more.

## Cost

$7.18 of paid judge calls; full spend, Codex retries and exclusions in
[`docs/methods.md`](../docs/methods.md) ([cost](../docs/methods.md#cost),
[reliability](../docs/methods.md#reliability),
[exclusions](../docs/methods.md#trials-and-exclusions)).

## Reproducing

Every table is rebuilt without model calls; the commands are in
[methods](../docs/methods.md#reproducing).

## Appendix: final messages of the not-done endpoints

The first and last 300 characters of each final message, verbatim from the frozen boundary files.

### Phase 1a, weak: c4-03-cobol-modernization

`phase1-weak/c4-03-cobol-modernization__3dQwiek/b01`, 1,204 characters.

First 300:

````text
Done. `/app/program.py` is written and verified.

What it does (mirroring program.cbl):
- Reads the single 22-byte input record (buyer, seller, book, PIC 9(10) amount) from src/INPUT.DAT; empty file → "Error: Input file is empty".
- Validates: buyer and seller exist in ACCOUNTS.DAT, book exists in B
````

Last 300:

````text
 warning differs, not program output).
- Files restored to the example's expected state afterwards; one note: the original 15-byte src/INPUT.DAT content was overwritten during testing (check_example.py restores its own inputs, so it's left as the example's last test case, which the checker accepts).
````

### Phase 1a, weak: c6-02-test-triage

`phase1-weak/c6-02-test-triage__GNhiNku/b01`, 1,536 characters.

First 300:

````text
All 15 tests pass. Report on the 5 that failed:

1. test_month_end_december (ERROR) — dates.py `month_end` built `date(year, month + 1, 1)`, which raises ValueError for December (month 13). Fixed: wrap to January 1 of the next year when month == 12.

2. test_thousands_separator (ERROR) — parse.py `p
````

Last 300:

````text
 half away from zero.

5. test_round_negative (FAIL) — same cause; ROUND_HALF_UP on Decimals rounds -1.005 to -1.01 as the docstring requires (Python's float round gave -1.00).

`splits` and the report module needed no changes — verified `split(Decimal("10.00"), 3)` still returns [3.34, 3.33, 3.33].
````

### Phase 1a, weak: c6-02-test-triage

`phase1-weak/c6-02-test-triage__vwAxV9J/b01`, 1,333 characters.

First 300:

````text
All 15 tests pass. Report on the 5 failures:

1. test_dates.test_month_end_december — `dates.month_end` built the first day of the next month as `date(year, month+1, 1)`, which raised `ValueError` for December (month 13). Fix: wrap to `date(year+1, 1, 1)` when month == 12.

2. test_parse.test_thousa
````

Last 300:

````text
re-Decimal `quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")`, which is also correct for the negative case.

5. test_money.test_round_negative — same root cause: `round()` is half-to-even and biased wrong for negatives; -1.005 gave -1.00 instead of -1.01. Fixed by the same ROUND_HALF_UP quantize.
````

### Phase 1a, weak: c6-02-test-triage

`phase1-weak/c6-02-test-triage__WAGrJ9F/b01`, 1,151 characters.

First 300:

````text
All 15 tests pass. Report on the 5 failures:

1. **test_round_half_up** (2.675 → expected 2.68): `round_cents` went through `float()`, where 2.675 is actually 2.67499…, so it rounded down. Fix: quantize the Decimal directly with `ROUND_HALF_UP` (which in the decimal module means half away from zero)
````

Last 300:

````text
* (100 USD → 92 EUR): `convert` multiplied by `rates[src]` and divided by `rates[dst]`, inverting the rate table (rates[c] = price of 1 USD in c). Fix: `usd = amount / rates[src]`, then `usd * rates[dst]`.

Also checked `split` and `report` — they already matched their docstrings; no changes needed.
````

### Phase 1a, strong: c2-01-rename-function

`phase1-strong/c2-01-rename-function__BusA9zA/b01`, 726 characters.

First 300:

````text
Done. All 4 tests pass and the only remaining `calc_total` references are intentional (the alias definition, its deprecation test, and the changelog/docs mentions).

Changes:
- billing/totals.py — renamed `calc_total` → `compute_total`; added `calc_total` as a deprecated alias that emits `Deprecatio
````

Last 300:

````text
l`.
- tests/test_totals.py — updated uses; added a test asserting the alias warns and returns the same result.
- docs/API.md — documented `compute_total` and the deprecated alias.
- CHANGELOG.md — added an "Unreleased" entry for the rename.

`python3 -m unittest discover -s tests` → Ran 4 tests, OK.
````

### Phase 1a, strong: c4-05-log-summary-date-ranges

`phase1-strong/c4-05-log-summary-date-ranges__3cDDSWh/b01`, 659 characters.

First 300:

````text
Done. /app/summary.csv written and passes `python3 /app/check_summary.py` (layout: ok).

Counts (severity parsed from each line's bracket tag `[ERROR]`/`[WARNING]`/`[INFO]`; file date from the filename, reference date 2025-08-12):

    period         ERROR  WARNING  INFO
    today             74    
````

Last 300:

````text
ast_30_days    2433     3263   9788
    month_to_date   1196     1614   4907
    total           3578     4764  14309

Note: severity is taken from the bracketed level only — "ERROR" also appears inside WARNING message text (e.g. "Next attempt will ERROR"), so a naive substring count would be wrong.
````

### Phase 1a, strong: c6-02-test-triage

`phase1-strong/c6-02-test-triage__hxonsj6/b01`, 2,258 characters.

First 300:

````text
All tests pass (15/15, exit 0). Report:

Test suite result: OK — 15 tests, 0 failures, 0 errors. Fixes were confined to `ledgerkit/`.

Failing tests and causes

1. test_dates.DatesTest.test_month_end_december
   Cause: `month_end` computed `date(day.year, day.month + 1, 1)`, which builds month 13 fo
````

Last 300:

````text
t]`), quantizing to cents. 100 USD → 92.00 EUR; same-currency conversion still returns the amount unchanged; unknown currency still raises `KeyError`.

The two tests already passing under report.py are untouched; `summarise` now benefits from the corrected `parse_amount` but needed no change itself.
````

### Phase 1a, strong: c6-02-test-triage

`phase1-strong/c6-02-test-triage__Py7J32g/b01`, 2,572 characters.

First 300:

````text
All 15 tests pass (`OK`, exit 0). Report on each test that failed originally:

**1. test_parse.test_thousands_separator — ERROR (ValueError: not an amount: '1,234.50')**
Cause: `parse_amount` only stripped `$` and whitespace, leaving the comma; `Decimal("1,234.50")` raised `InvalidOperation`, conver
````

Last 300:

````text
nteger cents with a sign-magnitude `divmod`, so all totals — positive and negative — now sum exactly, with earlier parts taking the extra cents. Verified: 10.00→[3.34,3.33,3.33], -10.00→[-3.34,-3.33,-3.33], 0.05→[0.02,0.02,0.01], 100.00/7 exact.

Final: 15/15 tests pass; no test files were modified.
````

### Phase 1a, strong: c6-02-test-triage

`phase1-strong/c6-02-test-triage__RDpUnTV/b01`, 1,873 characters.

First 300:

````text
All 15 tests pass now (`python3 -m unittest discover -s tests` → OK).

Report on the 5 tests that were failing:

1. test_month_end_december — test_dates.py
   Cause: month_end built the next month as date(day.year, day.month + 1, 1). For December that's month 13, which raises ValueError("month must 
````

Last 300:

````text
ts the conversion (100 USD → 108.70 EUR instead of 92.00).
   Fix: divide by rates[src] to get USD, then multiply by rates[dst]: usd = amount / rates[src]; return usd * rates[dst].

split (money.py), quarter (dates.py), and summarise (report.py) already matched their docstrings and needed no change.
````

### Phase 1b, weak: c2-03-release-bump, first boundary

`phase1b-weak-b/c2-03-release-bump__PAnkABR/b01`, 627 characters.

First 300:

````text
Release done. Version bumped to 1.5.0 in:

- pyproject.toml:3 (`version = "1.5.0"`)
- src/fluxq/__init__.py:3 (`__version__ = "1.5.0"`)
- docs/conf.py:5 (`release = "1.5.0"`)
- README.md:3 (badge → `version-1.5.0-blue`)

CHANGELOG.md now has an empty `## Unreleased` heading above `## 1.5.0 - 2026-10
````

Last 300:

````text
ormer Unreleased entries.

Deliberately left untouched: the `retrylib==1.4.2` pin (a dependency, not this package's version), the retrylib mentions in README/CHANGELOG, and `docs/conf.py`'s short `version = "1.4"` shorthand (not a declared 1.4.2 string — say the word if you want it bumped to "1.5").
````
