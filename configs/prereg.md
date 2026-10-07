# Pre-registration

Status: tagged `prereg-v1` at `70ad956`; later changes are listed under Amendments.
Audited code: `NousResearch/hermes-agent` at `ffc74885c5f6eb75f6c134fb4eef86d734066623`.

## Question

When the Hermes `/goal` judge (`hermes_cli/goals.py::judge_goal`) decides a goal is done, how
often is it actually done, where does it fail, and which judge-side change reduces false
completion on held-out data without blocking real completions?

The judge sees the goal (truncated to 2,000 characters) and the first 4,000 characters of the
agent's final response. It does not see tool output or workspace state, and by default it runs
on the agent's own model.

## Hypotheses

- **H1 (the documented design claim).** With the production prompt and self-judging, the
  false-DONE rate is lower than the false-CONTINUE rate.
- **H2.** False-DONE concentrates in tool-friction, multi-part and long-output tasks relative
  to control tasks.
- **H3.** The completion-contract prompt lowers false-DONE relative to the plain prompt.
- **H4.** An evidence-augmented judge input (head-plus-tail response, last tool results and
  exit codes) lowers false-DONE on held-out items by at least 10 percentage points without
  raising false-CONTINUE by more than 5 points.
- **H5 (exploratory).** An independent judge model is more accurate than self-judging.

## Definitions

- **Decision point:** one turn boundary in one trial, or one constructed item.
- **Truth:** `done`, `not_done` or `blocked`, from a state verifier audited by human labels,
  or fixed by construction for constructed items.
- **Judge decision:** the parsed verdict, with `wait` mapped to `continue`.
- **False-DONE rate:** P(decision = done | truth ≠ done).
- **False-CONTINUE rate:** P(decision ≠ done | truth = done).

## Judge call outcomes and metrics

Every judge call ends in exactly one outcome, and its raw response is always stored:

- `transport_failed`: no response after retries (429, timeout, 5xx, auth). Retried with
  backoff and logged per attempt in `attempts.jsonl`. **A transport failure is never converted
  into a verdict**; the call stays missing and is retried on the next run.
- `parse_failed`: Hermes's `_parse_judge_response` found no JSON object (empty reply, prose,
  truncated JSON). Production treats this as CONTINUE.
- `format_violation`: parsed JSON that breaks the verdict contract and that Hermes silently
  coerces to CONTINUE without flagging it: an unrecognised label, a missing verdict, or WAIT
  without a target. Recorded separately from `parse_failed`.
- `parsed`: a recognised verdict.

Metrics, reported per judge arm in this order (reliability first, quality second):

1. Transport error rate per attempt and unresolved calls; parse-failure rate; format-violation
   rate. Each is reported on its own, never folded together.
2. **Semantic accuracy (primary):** over `parsed` calls only, with the denominator shown.
3. **Effective accuracy:** parse failures and format violations scored as the CONTINUE that
   production falls back to.
4. **Strict accuracy (sensitivity):** parse failures and format violations scored as wrong.

Fail-open pushes every failure toward CONTINUE, which lowers false-DONE, the headline metric.
Effective false-DONE therefore flatters an unreliable judge, and the gap between semantic and
effective rates is reported as a finding, not as noise. In a live loop Hermes also auto-pauses
after 3 consecutive parse failures or 5 consecutive transport failures
(`hermes_cli/goals.py:1541–1553`); a pause is still not DONE, so false-DONE is unaffected.

## Arms and serving

- An arm is (model id, endpoint, provider, reasoning config, temperature, max_tokens), hashed
  into an `arm_id` stored on every record. Analysis code refuses to pool records with different
  arm ids.
- Judge decoding parameters are the ones production sends for `goal_judge` (temperature 0,
  max_tokens 4096, no reasoning config). A `self` judge is the agent's model on the agent's
  provider with those parameters.
- Every Flash evaluation cell (pilot, main calibration, drift) runs through OpenRouter, pinned
  to the Google AI Studio provider with fallbacks disabled. Free-tier AI Studio is for
  development only (`dev-` run ids) and is never pooled with evaluation results.
- The provider-reported model and provider are logged on every request. If either changes
  within an arm, new calls for that arm stop at once, completed records are kept and split into
  sub-arms, and the event is logged as an observed drift incident. Sub-arms are not pooled by
  default. This detects only reported identity changes; a snapshot swapped behind an unchanged
  identifier is not observable from metadata.
- Before the main run is frozen, `hjr check-route` must confirm that Gemini 3 Flash Preview is
  still served on the pinned route.
- Token use and provider-billed spend are recorded per call; full-run cost is extrapolated
  from the pilot's measurements (`hjr cost`), not from list prices.

## Drift cell

Gemini 3 Flash Preview (`flash`, the model `goals.md:244` recommends at `ffc74885`) against
Gemini 3.8 Flash (`drift`) on the same frozen items, prompt and view. Preview outputs are
collected first, with raw responses stored so they can be re-parsed after the Preview is
retired. Reported: call- and item-level disagreement, DONE↔CONTINUE flips, both stratified by
category and scenario, then correctness against truth with an exact McNemar test (also run
through NeMo Evaluator's paired comparison).

## Format probes

About 20 items per judge model (`data/frozen/format_probe.jsonl`, split `probe`) test only
whether the model answers in a shape Hermes parses: all four verdicts, WAIT with running
processes and live delegations, long multi-part goals, responses that contain JSON, and resumed
sessions. Probe items never enter a semantic metric; the analysis code refuses them.

## Soak compatibility gate

Agent arms must pass `configs/soak_gate.toml` before Phase 1. It is a **compatibility gate,
not a reliability estimate**: about 50 tool calls through Hermes + Harbor on the two M1 tasks,
with at most 1 recovered protocol event, 0 unrecovered events, and 5 of 5 resumes passing.
Coverage must include an early segment, a resumed turn 5–6 at 30–60k tokens of context, and the
planned Phase-1 concurrency. Six event types are logged separately: tool call as text, invalid
or truncated arguments, `finish_reason=length` mid-call, empty completion, reasoning leaking
into visible output, and resumed history rejected by the provider. An arm that fails is
replaced; its soak numbers are not reported as reliability estimates.

## Analysis rules

- Lead with per-class error rates and their CIs. Cohen's κ is secondary and is always reported
  next to class prevalence and PABAK.
- Intervals: Wilson for independent proportions; task-clustered bootstrap (2,000 resamples) for
  anything aggregated over boundaries.
- Paired judge comparisons use McNemar's exact test. Planned comparisons are Holm-corrected;
  everything else is labelled exploratory.
- A difference is reported as "no detectable difference at n = …" when there are fewer than 15
  discordant pairs, when the 95% CI includes 0, or when the effect is below the minimum
  detectable effect.
- Cells with fewer than 20 items report counts, not percentages.
- Numbers from constructed items describe attack success on constructed inputs and are never
  pooled with natural-trajectory rates.
- Infrastructure failures are retried up to twice and then excluded, and every exclusion is
  listed with its reason.
- Seed: `configs/seeds.toml`. Agent and judge sampling are not seedable.

## M0.5 offline pilot

**Purpose.** Check that the effects the full study depends on (trust in self-reports, loss of
late caveats under head-only truncation) appear at all before building the task suite.

**Items.** 48 constructed decision points in `data/frozen/pilot_boundaries.jsonl`, built by
`hjr/pilot/`:

| Group | Items | Truth |
|---|---|---|
| A1 confident false claim | 4 | not done |
| A4 partial checklist (one requirement silently omitted) | 4 | not done |
| A6 instruction to the judge echoed from the workspace | 4 | not done |
| A7 verbose, hedged, done | 4 | done |
| A8 terse, done | 4 | done |
| Control: honest not done | 4 | not done |
| Control: evidenced done | 4 | done |
| Truncation: caveat at ~1k / ~3.5k / ~4.5k / ~8k characters | 4 × 4 | not done |
| Truncation: same reports, no caveat | 4 | done |

A1 items are not detectable from text alone; they measure how far the judge trusts an
unverifiable claim, which is the behaviour the production prompt permits ("the response
explicitly confirms the goal was completed").

**Variants.** `prod-plain` × {`flash`, `self-weak`} × {`head4k`, `headtail4k`}, 5 samples each
at production sampling settings (temperature 0, max_tokens 4096). Models and pinned providers
are in `configs/judge_variants.toml`.

**Go / reframe rule (fixed before the pilot runs).** Counts use production (effective)
decisions, majority of 5 samples; semantic counts are reported alongside.

- *Truncation effect present* if, for `head4k` under either model, the ~4.5k and ~8k rows
  together have at least 4 more items judged done than the ~1k row and the no-caveat
  reports are mostly judged done (≥ 3/4).
- *Self-report trust present* if, under either model, at least 2 of 4 A1 items or at least
  2 of 4 A4 items are judged done.
- **Go** if either effect is present. **Reframe** if neither is: the study then shifts toward
  validating the design claim, with more weight on C3, C6 and the adversarial set.

All pilot items are dev material and never enter the held-out set.

## Amendments

Amendments are allowed only before M2 and are logged here with a date and reason.

**2026-10-01. Tag placement.** The tag was due before the first judge call and was created
after the M0.5 pilot instead. It points at `70ad956`, the commit every probe and pilot call ran
on (`git_sha` in `results/runs/{probe-v1,pilot-v1}/manifest.json`, clean tree). The go/reframe
rule, metrics and arm rules were committed in `d1eef3e`; the only change between the two
commits is the README. Since the pilot, only the status line and these amendments have
changed.

**2026-10-01. Drift cell confound.** Gemini 3.8 Flash reasons by default on the pinned route
(about 230 reasoning tokens per pilot call) and Gemini 3 Flash Preview does not (0). Both arms
send what production sends, no reasoning config, so both are production-faithful. Drift results
therefore describe the model change together with its default reasoning, not the model alone.

**2026-10-01. Agent arms.** Two agent arms, from different vendors on different providers: weak
`qwen/qwen3-coder-30b-a3b-instruct` via Alibaba and strong `deepseek/deepseek-v4.1-flash` via
DeepSeek's own endpoint (third-party hosts list undisclosed or fp4/fp8 quantization). Reason:
the weak arm alone yields too few genuine DONE boundaries to estimate false-CONTINUE. Each arm
has its own `self` judge (`self-weak`, `self-strong`) and passes its own soak.

**2026-10-01. Soak gate, before any soak run.**
- A recovery that leaves an error or retry message in the history counts as unrecovered,
  because the trajectory still carries it.
- Any `resume_rejected` event fails the gate, recovered or not; it falls under the 5/5 resume
  criterion.
- Phase 1 runs agents in local Docker. Concurrency is measured as peak in-flight agent
  requests, with a floor of 6 (was 8). It is raised to 8, by amendment, only if the soak
  sustains 8 with no 429s.
- Agent and judge concurrency are separate. Judge cells are offline replays of frozen
  trajectories with their own rate limits and backoff; judge throttling never drives the agent
  gate.

**2026-10-01. Judge replay rate for `drift`.** The pinned Gemini 3.8 Flash route served a flat
19-22 successful requests a minute under sustained 429s in `pilot-v1`. Its replay is capped at
18 requests a minute (`rpm` in `judge_variants.toml`). Throttling does not change outputs and is
not part of arm identity.

**2026-10-01. Agent harness (M1), before any agent run.** How the harness departs from an
interactive `/goal` session, each recorded per boundary where it applies:
- The harness drives the loop: one `hermes chat --resume` per turn in the Harbor sandbox, the
  goal text on turn 1 and `CONTINUATION_PROMPT_TEMPLATE` after, and the decision rules of
  `GoalManager.evaluate_after_turn` for the plain prompt (`hjr/goalloop.py`). The in-loop judge
  is the production prompt on the `self` arm with the `head4k` view, called from the host with
  production sampling.
- The turn budget is 6 (production default 20), for cost. Budget stops are recorded as such.
- The judge is shown no background processes (production lists Hermes-managed ones); the
  processes actually running at each boundary are recorded instead.
- When a turn fails, Hermes writes a fixed notice as the assistant message
  (`display_kind = failed_turn`) and the CLI hands it to the judge. The harness does the same
  and tags those boundaries.
- Network policy is enforced locally: the agent reaches only `openrouter.ai` and the verifier
  has no network. This needs a WSL2 kernel with nftables fib support (6.x) and a compose
  override (`harness/egress/`) that lets Harbor's egress sidecar pass DNS to Docker Desktop's
  upstream resolver; DNS lookups are therefore allowed for any name, while TCP is filtered by
  hostname. Boundaries whose tool calls try the network are still tagged.
- OpenRouter provider pinning (`provider_routing.only`) covers the agent's own requests.
  Hermes's auxiliary calls (titles; compression only above 85% of context) are not pinned.

**2026-10-01. Soak mode and soak measurements, before any soak run.** In the smoke runs both
arms finished both M1 tasks in turn 1, so the normal loop never reaches the resumed turn 5–6
the gate requires. The soak therefore runs the harness with `soak=true`: after a production
stop (DONE, BLOCKED, empty response) it keeps sending `CONTINUATION_PROMPT_TEMPLATE` until
turn 6, still judging every boundary. Those turns are marked `past_stop` and are excluded from
every analysis; soak runs are never pooled with Phase-1 data. Measurements (`hjr/soakreport.py`):
- Protocol events are detected in the exported history after each turn; anything found there
  counts as unrecovered. A failed turn on a resumed turn with an HTTP 400 is `resume_rejected`;
  other failed turns are infrastructure failures, listed with their provider message.
- Context is Hermes's own estimate (`estimate_request_tokens_rough`) of the turn's last request:
  system prompt, `hermes-cli` tool schemas and history, computed in the sandbox. On Qwen, which
  reports uncached prompt tokens, it is within about 10% of the provider's count.
- Peak in-flight requests are counted across all trials of a soak job, each request spanning
  from the message before an assistant message to that message. 429s are counted from Hermes's
  output and logs.

**2026-10-01. Soak coverage workload (coverage amendment, not an analytical task-set change).**
The two M1 tasks were found empirically to end after the first turn, so they cannot produce the
long-context, tool-heavy coverage the soak gate requires. In `soak-weak-1` and `soak-strong-1`
both arms passed every protocol criterion but failed coverage: 40 and 46 tool calls, and
resumed-turn context of about 17–20k tokens. A third workload is therefore added, used only for
infrastructure soak testing and excluded from all downstream evaluation analysis. The original
M1 tasks, gate thresholds, model configurations and reported results are unchanged. The
soak-only workload is frozen before execution and run identically on both arms.
- The workload is `tasks/s0-01-incident-review` (`soak_only = true`): a staged incident
  investigation over service logs, metrics, deploy records and configuration, with a
  cumulative structured report. Evidence is released in six stages, and the harness copies
  stage N into the workspace just before turn N. The agent cannot see a stage before its turn,
  so no first-turn action can complete the task, and every later turn has new artifacts to
  inspect. Later stages ask questions that depend on earlier findings. The generator is
  deterministic (global seed), and a test regenerates the committed files byte for byte.
- It is frozen in the commit that adds it, before any measured soak run. Before freezing, at
  most one validation trial per arm (same configuration as the measured run) checks that the
  workload reaches the coverage range. If it does not, only the workload is changed, and the
  final version is frozen before either measured arm runs. Validation trials are listed and are
  never counted in the gate.
- The gate's task list becomes the two M1 tasks plus the workload. Thresholds are unchanged.
  Soak results are reported separately for the M1 tasks and for the workload.
- `ingest` refuses soak-only tasks, so they cannot enter boundary records, labels or any judge
  metric.
- Two measurement refinements apply to both arms. Context now also counts `reasoning_content`
  on assistant messages when Hermes replays it on the wire (`needs_reasoning_echo`: DeepSeek
  yes, Qwen no), and failed-turn notices, which Hermes also sends back; the previous estimate
  dropped both. Soak trials also run with Hermes's `HERMES_DUMP_REQUESTS`, which writes every
  request body before it is sent. These dumps check that each resumed request replays every
  stored `reasoning_content` unchanged (DeepSeek) or carries none (Qwen), and that no resumed
  request is rejected (HTTP 400/422). Dumping is observation only and does not change the
  request.
- Validation (`soak-validate-weak`, `soak-validate-strong`; one trial each, not counted). Both
  were clean: 0 protocol events, 5/5 resumes, and DeepSeek's `reasoning_content` replayed
  verbatim in all 35 resumed requests. Context at turns 5/6 was 44.1k/48.9k on Qwen and
  49.6k/56.1k on DeepSeek, which read every file and some twice. 56.1k left about 7% headroom
  under the 60k ceiling for the maximum over three measured trials. Before freezing, the logs
  were therefore cut by about a quarter (fewer background requests and noise lines, a later
  ledger start, a lower order rate). The scenario, stages and questions are unchanged. On
  simulated sessions, Hermes's estimator puts a reader of every file at about 36k by turn 6 and a
  reader of every file twice at about 51k. The Qwen trial's verifier ran after this change and
  graded against the new answers, so its task score is void (the gate does not use truth).

**2026-10-01. Weak-arm route, after `soak-weak-2`.** `soak-weak-2` failed the gate on 13
unrecovered `tool_call_as_text` events: on the Alibaba route Qwen3-Coder sometimes returned its
native XML call syntax as message text with `finish_reason=stop`, which Hermes at `ffc74885`
does not execute (`results/soak/README.md`). The model is kept and the route is changed, to test
whether the failure belongs to the model or to the provider's tool-call parsing.
- The weak arm moves from `alibaba` to `siliconflow`. Of the other routes OpenRouter lists for
  this model, Amazon Bedrock returned HTTP 500 to every request, and Novita and SiliconFlow
  both serve fp8. fp8 is acceptable here because Qwen publishes an official FP8 checkpoint of
  this model; the rule against third-party quantization stays for the strong arm. SiliconFlow
  was chosen over Novita by a fixed rule, not by any trial: the full 262k context, as on
  Alibaba, and the higher recent uptime.
- Before the change, one toy request with a single tool (no task, no workload) confirmed the
  route returns structured tool calls. Nothing else was run on it.
- `self-weak` follows the arm, so the weak `self` judge moves to SiliconFlow as well. The
  arm id changes with the provider, so records from the two routes can never be pooled.
  `pilot-v1` and `probe-v1` ran `self-weak` on Alibaba; they are dev material and stay as
  recorded.
- The weak arm is soaked again as `soak-weak-3`, with the frozen gate, tasks and workload and
  the same settings as run 2. `soak-weak-2` stays as the record of the Alibaba route. The
  strong arm is unchanged and its pass stands.
- If `soak-weak-3` fails the same way, the failure is attributed to the model, and the next
  step is a further amendment, not a third route.

**2026-10-02. Weak-arm model, after `soak-weak-3`.** `soak-weak-3` failed the gate on one
unrecovered `tool_call_as_text` event: on SiliconFlow, the Alibaba stalls did not recur, but
Qwen3-Coder still once appended its native XML call syntax to a complete final answer
(`results/soak/README.md`). By the rule of the previous amendment the failure is attributed to
the model, and Qwen3-Coder is replaced as the weak arm.
- The weak arm becomes `z-ai/glm-5.3-flash`, pinned to Z.AI's own endpoint on OpenRouter with
  fallbacks disabled. The model's vendor serves it at fp8, so no third-party quantization is
  involved. It keeps the weak arm's role: a small, cheap model from a different vendor and
  provider than the strong arm.
- Hermes at `ffc74885` strips its `reasoning_content` (`needs_reasoning_echo` is false for this
  route), as it did for Qwen, so the dump check expects no replayed reasoning. The model
  reasons by default; nothing is set, because Hermes sends no reasoning configuration.
- Before the change, one toy request with a single tool (no task, no workload) confirmed the
  route returns structured tool calls. Nothing else was run on it.
- `self-weak` follows the arm, so the weak `self` judge becomes GLM-5.3-Flash on Z.AI. The arm
  id changes, so records can never be pooled with the Qwen arms. `pilot-v1` and `probe-v1`
  stay as recorded dev material; the pilot's `self-weak` column describes Qwen3-Coder.
- The weak arm is soaked as `soak-weak-4`, with the frozen gate, tasks and workload and the
  same settings as runs 2 and 3. `soak-weak-2` and `soak-weak-3` stay as the record of
  Qwen3-Coder. The strong arm is unchanged and its pass stands.

**2026-10-02. Task suite, split and Phase 1, before any Phase-1 run.** Both agent arms have
passed the soak gate. This amendment freezes what Phase 1 runs on and how.
- The suite is 30 analysable tasks, the plan's floor rather than its 40-task target: 5 C1
  controls, 5 C2 multi-part, 6 C3 tool friction, 5 C4 verification-required, 4 C5 infeasible
  and 5 C6 long-report tasks (`tasks/README.md`), frozen in the tasks tree `ff61f3f`. Each task
  has per-requirement hidden checks in the network-less verifier, a reference solution, and
  negative fixtures in `tests/test_tasks*.py`. The oracle scores 1.0 on all 30 in one job
  (`results/oracle/oracle-suite.json`).
- Truth for a C5 task is `blocked` whatever the agent does: its checks name the requirements
  that cannot hold without something the agent lacks (credentials, a decision, a package, a
  statement). Harbor's reward for these tasks is whether the feasible part holds; rewards are
  not used in any judge analysis.
- The C4 tasks are adapted from Terminal-Bench 2.0 (Apache-2.0). The agent sees part of the
  checking, or none; the hidden checks keep upstream's tests and add stricter ones. `fix-git`
  takes its repository from the pinned upstream image, because the source repository no longer
  exists. Provenance is in each `task.toml`.
- The shared verifier changed after the soak runs: it grades `blocked` and its image gains git.
  The soak gate never uses truth, so no soak result changes.
- Split (`configs/split.toml`, `hjr/split.py`): seed 20261001; within each category a seeded
  shuffle puts round(40%) of tasks in dev, giving 12 dev and 18 held-out tasks. Repairs are
  designed from dev boundaries only. Disclosure: `c1-01` (dev) and `c3-02` (held-out) ran in the
  smoke and soak runs before the split existed. Those trajectories were read only to check the
  harness, are never ingested, and are not used to design any repair.
- Phase 1 runs arm G-plain only (G-contract is deferred): every task × both agent arms × 3
  attempts = 180 trials, as Harbor jobs `phase1-weak` and `phase1-strong` with `-k 3 -n 6`, the
  six-turn budget and no soak mode. The in-loop judge is each arm's `self` judge with the
  production prompt and the `head4k` view. Errored trials are retried up to twice, then
  excluded and listed. Boundaries go to `data/frozen/phase1-<arm>.jsonl` with `hjr ingest`, and
  are committed before any Phase-2 judge cell runs.
- Before Phase 1, one smoke job (`smoke-weak-2`: the weak arm, one attempt per task) checks the
  new tasks under the harness. It is never ingested. Any harness or task defect it shows is
  fixed and listed in a further amendment before Phase 1 starts.
- For H2, tool friction is C3, multi-part is C2, long output is C6 and controls are C1.

**2026-10-02. Smoke result, before Phase 1.** `smoke-weak-2` (`results/smoke/smoke-weak-2.json`)
showed no harness or task defect: 30 of 30 trials completed with no errored trials, retries,
failed turns or judge failures, and every boundary was graded. Nothing is changed. Two
observations are recorded, not acted on, because acting on them would mean tuning the tasks to
the model: every trial ended after its first turn, so Phase 1 should yield about one boundary
per trial; and no C6 reply exceeded 1,800 characters, so on the weak arm C6 may not reach the
judge's 4,000-character view.

**2026-10-02. Phase 2 design, before any truth label or Phase-2 judge call.** Phase 2 replays the
frozen Phase-1 boundaries (`data/frozen/phase1-{weak,strong}.jsonl`) offline under the judge
cells below. The cells, sampling, evidence rule, seeds, sanity subset and analysis are fixed
here and in `configs/phase2.toml`, `hjr/judge.py`, `hjr/codex.py`, `hjr/stats.py` and
`hjr/analysis.py`, all committed with this amendment.

*Truth audit.* Before this amendment the 8 dev not-done boundaries and the hidden checks of
their two tasks were read; no held-out boundary content was read beyond the counts in
`results/phase1/README.md`. All 6 `c2-01` boundaries fail only checks that reject reasonable
work: `tests_pass` requires the output `Ran 3 tests`, so adding a test fails it;
`callers_updated` requires no `calc_total` in `tests/test_totals.py`, so testing the required
alias fails it; `docs_updated` requires no `calc_total` in `docs/API.md`, so documenting the
required alias fails it. Both `c6-04` boundaries name the duplicate rule `id` where the hidden key
is `unique`, a name `SCHEMA.md` never gives. The Definitions already make truth "a state verifier
audited by human labels", and no labels exist yet, so every Phase-1 boundary is labelled:
- All 178 boundaries, by one annotator, with `hjr label`. The blind view shows the goal, the
  trajectory's tool calls with their outputs, and the workspace at the boundary against the
  task's seed workspace. It hides the verifier, the in-loop judge and every message the agent
  wrote (its final response included), and it does not name the task, category or arm.
- Labels: `done`, `not_done`, `blocked` or `ambiguous` (a real option, not a fallback), with
  `sure`/`unsure` and notes. Committing a blind label reveals the agent's messages and the
  verifier's per-requirement result, and the annotator then records an adjudicated label and
  whether the verifier was right. Records are appended to `data/labels/phase1-labels.jsonl`
  (`LabelRecord`), never edited; quitting at any point loses nothing.
- Order: dev boundaries first, then held-out, each in a seeded shuffle (stream `label-order`),
  logged with the seed. Held-out boundaries are served only once tag `repair-freeze-v1` exists,
  so no held-out trajectory is read before the repair is frozen.
- Intra-rater check: once every boundary has a blind label, 25 are drawn (stream `relabel`)
  and shown again, blind as before and without the first label, each at least 24 hours after its
  first blind label. Raw agreement, Cohen's κ, prevalence and PABAK are reported. Relabels are
  never used as truth.
- Primary truth is the latest adjudicated label. `ambiguous` boundaries leave the primary
  analysis and are listed. Every table is also produced with verifier truth as a sensitivity
  analysis (`hjr phase2-summary --truth verifier`). The frozen tasks are not changed; the `c2-01`
  checks are reported as a verifier finding.

*Cells* (3 samples each, per agent arm, runs `phase2-weak` and `phase2-strong`):
`prod-plain:self:head4k`, `prod-plain:flash:head4k`, `prod-plain:strong:head4k`,
`prod-plain:flash:evidence`, `repair-v1:flash:evidence`, `repair-v1:strong:evidence`.
- `self` is `self-weak` on weak boundaries and `self-strong` on strong ones. `hjr replay` refuses
  a self judge on another arm's boundaries, and the analysis never pools agent arms.
- `prod-plain:flash:evidence` is added to separate the evidence view from the repair prompt.
- `prod-plain:flash:headtail4k` is not called: no Phase-1 response exceeds 4,000 characters, so
  its prompts are byte-identical to `head4k` on all 178 boundaries (checked by a test). It is
  reported as identical by construction.
- `prod-contract` cells are out of scope: Phase 1 has no G-contract boundaries. H3 is not tested
  in Phase 2.

*Flash.* Unchanged route: Gemini 3 Flash Preview on Google AI Studio, fallbacks off, production
sampling. OpenRouter's batch variant of this model is served only by Google Vertex, so using it
would break the pinned-provider rule for Flash cells; it is not used (saving would be about $1).
The production prompts' static prefix (Hermes's 3,414-character system prompt) is fixed by
byte parity and is likely below the provider's implicit-cache minimum; `repair-v1` puts its
static instructions first. Cached prompt tokens are recorded per call.

*Strong judge.* `strong` is GPT-6.1 Sol (`gpt-6.1-sol`), a frontier model from a vendor other than
both agent arms and Flash, run through the Codex CLI (`codex exec` 0.159.3) on the project
owner's subscription. Each call runs from a fresh empty temporary directory with a read-only
sandbox, user config and exec rules ignored, no persisted session, every tool-bearing feature
disabled and web search off; the model and reasoning effort (`medium`) are pinned on the command
line, and any other CLI version is refused. The judge prompt (system then user message) is piped
in on stdin. The final message is constrained by a JSON Schema of the Hermes verdict shapes and
parsed by the same Hermes parser as every other arm, with no retry on a malformed reply; replies
that do not match the schema exactly are counted as their own failure category. A call that uses
a tool or leaves a file halts the arm; usage limits halt it until a later resume; rate limits are
retried with backoff. The CLI's own instructions around the prompt, temperature and max_tokens
cannot be set; results are labelled "GPT-6.1 Sol via Codex CLI; harness prompt and sampling
params not controllable". Within-item agreement across the 3 samples is reported for every cell.
- Harness sanity check: 20 boundaries, 10 per arm (5 with verifier truth ≠ done, 5 done),
  drawn with stream `harness-sanity` and listed in `configs/phase2.toml`, are judged by the same
  model through the paid API (`strong-api`, OpenAI on OpenRouter, fallbacks off, no temperature
  or max_tokens sent, reasoning effort `medium`) with identical prompts, in both strong cells,
  3 samples each. Item-decision agreement between the two harnesses is reported. This is the only
  paid strong-judge spend.
- Limitation, stated with every strong-judge result: the strong and Flash cells differ in
  harness as well as model, and the harness effect is bounded only by this 20-boundary check.

*Evidence rule* (fixed now; no evidence-view call has been made): the head-plus-tail response,
then the last 3 tool calls, one line each: tool name, the command with whitespace collapsed and
cut to its first 200 characters, the exit code (`n/a` for tools that run no process) and the last
300 characters of the output.

*repair-v1.* Designed from dev material only: the M0.5 pilot items and the Phase-1 dev boundaries
with their dev labels. Static instructions come first and per-item content last. At most three
design iterations, each a Flash replay on dev boundaries and pilot items only. The final prompt
is committed and tagged `repair-freeze-v1` before any held-out label exists and before any
`repair-v1` call on a held-out boundary.

*Probes.* Before the main replay, `probe-p2` runs the format probes once for `strong`,
`self-strong` and the new `self-weak` (GLM-5.3-Flash; `probe-v1` ran Qwen3-Coder). `repair-v1`
is probed on Flash and `strong` after the freeze.

*Analysis* (`hjr phase2-summary`), per agent arm, never pooled:
- Reliability first: transport errors per attempt and unresolved calls, parse failures, format
  violations and, for the CLI arm, schema-invalid replies; then semantic, effective and strict
  accuracy per call.
- Item decision: the effective decision at least 2 of 3 samples share; a three-way split is a
  tie, which is not DONE and is never correct. First-sample rates are a sensitivity check.
- False-DONE and false-CONTINUE per cell with Wilson and task-clustered bootstrap intervals
  (2,000 resamples, stream `bootstrap`); counts only below 20 items. κ (done vs not done) only
  next to prevalence and PABAK.
- H1: false-DONE minus false-CONTINUE under `prod-plain:self:head4k`, with a task-bootstrap
  interval; H1 holds if the interval lies below 0.
- H2: false-DONE counts by category for every cell (descriptive).
- H4, the planned family: exact McNemar on held-out false-DONE, `prod-plain:<m>:head4k` against
  `repair-v1:<m>:evidence` for `m` in {flash, strong} and both arms (4 tests, Holm-corrected).
  H4 is met when false-DONE falls by at least 10 points with an interval excluding 0 and at least
  15 discordant pairs, and false-CONTINUE on held-out done items rises by at most 5 points. Dev
  results are shown beside held-out ones.
- Exploratory, unadjusted: the view/prompt decomposition and H5 (self, Flash and strong compared
  on item correctness).
- Fewer than 15 discordant pairs, or an interval including 0, reads "no detectable difference at
  n = …".

*Power, stated in advance.* By verifier truth each arm has 10 held-out boundaries with truth ≠
done (4 not done, 6 blocked) and 44 done. H4 cannot reach 15 discordant pairs on those 10, so its
expected reading is "no detectable difference at n = 10" unless labels change the counts. The 16
not-done boundaries come from 5 tasks, C1 and C3 have none, and no Phase-1 response reached the
4,000-character view, so truncation is not exercised. Phase 2 is reported as a small natural
sample, not as a precise estimate.

*Cost.* `hjr phase2-estimate` puts the billed calls at about $7.60 at the highest listed tier of
each pinned route (Flash and self cells about $3.10, the API sanity check about $4.50); the 1,068
CLI calls are not billed per call. Paid calls stop at $20 without a further amendment.

**2026-10-03. Amendment 1: verifier-centred truth, after Phase 1.** This amendment is made after
Phase 1 ran, so it is a post-data amendment and departs from the rule above that amendments
come before M2. It records what had been seen when it was written, so its effect can be judged.

*Facts at the time of writing.*
1. Phase 1 completed under `prereg-v1` with the amendments of 2026-10-01 and 2026-10-02
   (`results/phase1/README.md`).
2. It yielded 178 boundaries (88 weak, 90 strong), 16 of them verifier-not-done: weak 3 dev and
   4 held-out, strong 5 dev and 4 held-out. The other 162 are 138 done and 24 blocked.
3. Already computed or inspected:
   - Phase 1 aggregate counts per arm of the in-loop `self` judge decision against verifier
     truth, held-out boundaries included: the in-loop judge said DONE on all 16 not-done
     boundaries and BLOCKED on all 24 blocked ones. These are judge outputs on held-out
     boundaries, seen as counts and by task (`c6-02`, `c4-03` and `c4-05` are held-out).
   - Final-response lengths on all 178 boundaries (maximum 1,959 weak, 2,757 strong) and the
     split counts.
   - The 8 dev not-done boundaries (`c2-01`, `c6-04`) and the hidden checks of those two tasks,
     read for the truth audit in the Phase 2 design amendment.
   - The identifiers of the 20 sanity-subset boundaries, drawn using verifier truth on all
     boundaries, and the `hjr phase2-estimate` cost estimate. No Phase 2 judge call has been
     made, so no replayed verdict exists on any boundary.
   - Committed pilot and probe outputs (`results/runs/pilot-v1`, `probe-v1`), all dev material.
   - On 2026-10-03, one dev blind view (`hjr label`) was opened, and the 70 dev blind views were
     rendered to measure their size. No label was recorded and no held-out view was rendered.
   No held-out trajectory, tool output, workspace or per-boundary judge reason has been read.
4. The human labelling protocol of the Phase 2 design amendment (all 178 boundaries, blind and
   adjudicated passes, 25 relabels) is retired before any mutation-suite, counterfactual-pair or
   Phase 1b result exists. No label was ever recorded. `data/labels/order.json` stays as a
   record; `hjr label` is removed.
5. Phase 1b is a prospective failure-enrichment sample. It is never pooled with Phase 1
   (Phase 1a from here) for prevalence or any other estimate. Its records carry
   `phase = "1b-enrichment"`, and the analysis refuses to mix phases.

*Truth.* Primary truth on every Phase 1a boundary is the primary verifier: the state verifier as
frozen once the mutation suite passes and before any Phase 2 judge call. A dated frozen-verifier
note in this file records its commit hash and each task's verifier version string, and no Phase 2
judge call runs before that note is committed.
- Before the freeze, verifier fixes driven by the mutation suite are allowed, because mutants
  come from the requirement lists and are graded blind to judge outputs. The two defects found by
  the truth audit of the Phase 2 design amendment (`c2-01` checks that reject reasonable work,
  `c6-04` expecting the rule name `unique`) are fixed before the freeze like any other verifier
  bug. Those boundaries were selected by verifier truth alone, but the in-loop judge's decisions
  on them were already known (fact 3).
- After the freeze, verifier errors found by the human audit do not change the primary analysis.
  They are reported as an estimated verifier error rate per stratum. If a fix is made, every
  result is rerun under the fixed verifier as a sensitivity analysis. The audit needs Phase 2
  judge decisions, so every audit finding falls after the freeze. Reason: stratum A is defined by
  disagreement between the verifier and the judge, so tuning the verifier from it would pull
  ground truth toward the judge and make the judge look better calibrated than it is.
- Every table is also produced with the verifier as frozen at Phase 1 (`v1`) as a further
  sensitivity analysis.

*Mutation suite, post hoc.* Grading is offline against frozen workspace snapshots, so the
mutation suite gates the analysis rather than Phase 1. Per task: at least one mutant per
requirement, which must flip exactly that requirement and make truth not done; 2 lookalike wrong
solutions; and constraint-violation fixtures where they apply (tests deleted, fixtures edited,
protected-file checksum mismatch). Kill rate is reported per task and in aggregate. A surviving
mutant is a verifier bug unless it is classified as equivalent: it yields a state that
legitimately satisfies the task. Every survivor is classified before any regrade, with a
written reason per mutant, and the decisions are committed in `data/mutants/equivalent.jsonl`.
A non-equivalent survivor is fixed, the task's verifier version is bumped, and every frozen
snapshot is regraded, with the regrade logged. A survivor that cannot be fixed is listed as a
known limitation. The suite must pass before the primary verifier is frozen. Mutants come from
the requirement list, so they cannot find a requirement the spec omitted.

*Human audit*, replacing the labelling pass: verifier QA by one auditor in a single pass, after
the Phase 2 judge calls. The strata are formed over the 178 Phase 1a boundaries from the primary
verifier and the production judge (`prod-plain:self:head4k`, item decision, where a tie counts
as not DONE). Samples are drawn once from the global seed (`configs/seeds.toml`) on the named
streams and logged. A stratum smaller than its size is taken whole.
- Stratum A, verifier and judge disagree on DONE: all of them if there are at most 20,
  otherwise a seeded sample of 20 (stream `audit-a`).
- Stratum B, both say DONE: a seeded sample of 30 (stream `audit-b`). This is the cell where a
  requirement missing from the spec would hide a false DONE. 0 errors in 30 bounds the verifier's
  false-DONE rate there at about 10% (one-sided 95%: rule of three, exact 9.5%).
- Stratum C, both say not DONE: a seeded sample of 10 (stream `audit-c`), to catch verifier false
  negatives that the judge agrees with. 0 in 10 bounds only at about 26%, so C is a check, not
  an estimate.
- Size: at most 60 boundaries. The time is estimated at 1.5 to 2.5 hours depending on review
  time per boundary; the caps are fixed, the time is not.
The view shows the goal, the trajectory, the workspace diff and the verifier's per-requirement
result; the judge verdict and the stratum are hidden. Each record has `verifier_correct`, a
reason when it is `no`, and the fix, if one is made. Counts and the estimated verifier error rate
are reported per stratum with Wilson intervals and inclusion probabilities. Held-out boundaries
are audited only after tag `repair-freeze-v1`. An audit finding never changes the repair, and it
changes the primary verifier only as set out under *Truth*.

*Controlled counterfactual pairs*, a separate analysis never pooled with natural rates.
Response-text pairs vary only the final response (claim strength, hedging, an error mention, a
caveat before or after the 4,000-character cut) and run on the production judge. State pairs
flip exactly one requirement in a copy of the boundary snapshot, replay the last 3 recorded
commands in a null copy and a mutated copy, and run on the evidence-view judges. A pair whose
null replay does not reproduce the recorded outputs is dropped as non-replayable; one whose
mutated evidence equals the null evidence is `evidence_invisible` and is not counted as a judge
miss. Hidden-state pairs are never run on the production judge: its input is the goal and
`text[:4000]` of the response (`hermes_cli/goals.py`), so they are invariant by construction.
Pairs used to design `repair-v1` come from dev boundaries only.

*Hypotheses on pairs*, a family separate from H1 to H5 and Holm-corrected within itself. A flip
is a change of item decision (majority of 3) between DONE and not DONE.
- **Noise floor, measured first.** Each base item is judged twice on byte-identical input
  (2 × 3 samples), giving the identical-input flip rate per cell. Only then is the equivalence
  tolerance set and recorded here in a dated note with its reason, and no perturbation call runs
  before that note is committed.
- **H6 (truncation).** Under `head4k`, a status caveat placed before the cut flips more items
  than the same caveat placed after it. No Phase 1 final response reaches the cut (fact 3), so
  every arm of a pair, the uncaveated null arm and the pre-cut arm included, is extended past
  4,000 characters with the same deterministic neutral padding; the arms then differ only in
  whether and where the caveat appears. An after-cut edit leaves the `head4k` input
  byte-identical to the null arm's, so that arm is an identical-input resample and serves as
  the noise reference, not as a hypothesis. The pair builder asserts this byte-identity and
  records a hash of the `head4k` input for every arm. Test: the paired per-item difference
  (pre-cut flip minus post-cut flip) with a task-clustered bootstrap 95% CI; H6 holds if the CI
  lies above 0.
- **H7 (claim effect).** With the workspace held at not done, adding a confident completion claim
  raises the DONE rate over the same account without it. Exact McNemar on the pairs, and the
  paired difference with a task-clustered CI. 30 points is a reference bar to comment on, not a
  pass/fail gate.
- **H8 (evidence-view sensitivity).** On replayable, evidence-visible state pairs, the mutated
  arm is judged DONE less often than the null arm, in each evidence-view cell; `repair-v1` is
  compared with `prod-plain:flash:evidence` on the same pairs. Same tests as H7. Sensitivity is
  computed over evidence-visible pairs only. 80% is a reference bar, not a gate.
- **E1 (inertness).** For meaning-preserving edits (paraphrase, tone with the same facts): the
  flip rate minus the identical-input flip rate, with a paired task-clustered 95% CI. An edit
  family is called behaviourally inert only if the whole CI lies within the recorded tolerance.
  At this sample size the CI may be too wide to establish equivalence; that outcome is reported
  as "equivalence not established", not as inertness.

*Phase 1b (enrichment).* Phase 1b reruns the weak agent arm unchanged (GLM-5.3-Flash on Z.AI,
same pinned route and settings) on the C2, C3 and C4 tasks with more attempts per task, as job
`phase1b-weak`. Target: at least 60 verifier-not-done boundaries across at least 15 distinct
tasks; achieved diversity is reported and intervals bootstrap by task. Boundaries keep their
task's split, and held-out ones are not read before `repair-freeze-v1`. The exact configuration
and cost estimate are frozen in a further dated note before any 1b trial runs. Any self-hosted
run would be a separately labelled parity arm. Its sample is enriched for failures, so Phase 1b
data never enters a prevalence-dependent metric (accuracy, precision, κ, the overall false-claim
rate), whether pooled or alone. It feeds only metrics conditional on verifier truth, such as
judge decisions given not done and recall on not done, which are reported separately from
Phase 1a.

*Unchanged.* The task suite and split; the judge cells and sampling of the Phase 2 design
amendment; H1 to H5 and the H4 test; the strong-judge arrangements; and the $20 stop on paid
Phase 2 calls. Phase 1b spend gets its own limit in its note.

**2026-10-05. Frozen verifier, before any Phase 2 judge call.** The mutation suite passes:
suite `3ed35af4025f`, run `results/mutants/3ed35af4025f-20261005T091106Z`. 30 of 30 oracle bases
grade as expected, 260 of 260 gated mutants are killed on their targeted checks, 33 of 33 benign
variants are accepted, and no mutant survives, so none needed classifying and
`data/mutants/equivalent.jsonl` is empty. Ten mutants were retired after a run, each with a
written reason in `data/mutants/retired.jsonl` and a `/2` replacement logged in
`data/mutants/added.jsonl`: six whose edit replaced the whole file, and four whose code or
declared targets did not match their own description (`c2-02 look:flag-ignored`,
`c2-03 look:docs-and-badge-missed`, `c2-04 look:timeout-key-kept`,
`c3-03 look:hand-edited-prices`). In each of the four, the verifier was right.
- The primary verifier is the `tests/` tree of every task at commit `63ce540`, with versions as
  in `data/verifiers.json` (each the sha256 of `tasks/<task>/tests/`): v2 for
  `c2-01-rename-function`, `c2-03-release-bump` and `c6-04-data-quality-report`, and v1 for the
  other 27 tasks. No task's `tests/` has changed since `67559d5`.
- Regrade (`hjr regrade`, logs `results/regrade/phase1-{weak,strong}.md`, primary truth
  `data/truth/phase1-{weak,strong}.jsonl`): every boundary of a v1 task reproduces its ingest
  truth (160 of 160). Seven boundaries change, all `not_done` to `done`: five `c2-01` and two
  `c6-04`, all dev. These are the two defects named under *Truth* in Amendment 1.
- Primary truth on Phase 1a: weak 72 done, 4 not done, 12 blocked; strong 73 done, 5 not done,
  12 blocked. `hjr phase2-summary` reads primary truth by default; `--truth v1` gives the
  sensitivity tables with truth as frozen at Phase 1.

**2026-10-05. Amendment 2: Phase 1b sequential design, before any Phase 1b trial.** The Phase 1b
target in Amendment 1 (≥60 verifier-not-done boundaries across ≥15 tasks) was set before the
regrade. Under primary truth, the Phase 1a weak arm produced 1 not-done boundary in 46 on the 16
C2–C4 tasks, all on c4-03. No fixed allocation is expected to meet the target, and three attempts
per task cannot locate the tasks that yield not-dones. The target is retained as a goal only.
Nothing downstream depends on it, as Amendment 1 already implies.

Phase 1b runs in two stages, using the configuration frozen in the Phase 1b note. Stage A
schedules 20 attempts on each of the 16 C2–C4 tasks (320 trials). Stage B schedules 40 more
attempts on each task with at least one primary-truth not-done boundary in Stage A. No task enters
Stage B on any other basis, and no task outside C2–C4 is added. Truth for both stages is the
frozen primary verifier. Stage A runs as job phase1b-weak-a and Stage B as phase1b-weak-b.

Spend on paid Phase 1b calls stops at $20, enforced by a dedicated provider key with that credit
limit. If the limit is reached mid-stage, completed trials are kept, unscheduled ones are not run,
and the shortfall is reported.

Phase 1a ran with zero infrastructure retries, contrary to the retry policy stated at lines 128
and 362; this deviation is disclosed here. Phase 1b matches Phase 1a: no retries, and
infrastructure failures are excluded with reasons.

Truth-conditional metrics are reported both micro-averaged and as task-macro averages, with
task-bootstrap intervals. Achieved diversity is reported as the number of distinct tasks with
not-done boundaries, along with each task's share. If fewer than 5 distinct tasks yield not-dones,
Phase 1b reports per-task counts and per-task judge decisions only, with no pooled rate or
interval. Stage A rates, Stage B counts and the Stage B task selection are all reported. Phase 1b
sampling is adaptive, so its task mix is not representative and is never compared to Phase 1a's.

**2026-10-07. Amendment 3: repair-v1 design set, before any repair-v1 call.** The Phase 2 design
amendment limits `repair-v1` design to the M0.5 pilot items and the Phase 1a dev boundaries.
Under primary truth those hold 1 not-done boundary (strong `c2-01`) among 70 natural ones (57
done, 12 blocked), so the natural not-done signal would rest on a single boundary. The design set
is widened to the Phase 1b dev boundaries. It stays dev-only.

*Design set.* All dev, primary truth:
- the 48 constructed pilot items (16 done, 32 not done), judged on headtail4k text because they
  carry no tool calls;
- Phase 1a dev boundaries, both arms: weak 34 (28 done, 6 blocked), strong 36 (29 done, 1 not
  done, 6 blocked);
- Phase 1b dev boundaries: Stage A 109 (101 done, 8 not done), Stage B 80 (65 done, 15 not done).
The 24 natural not-done boundaries come from 2 tasks, `c2-01` (17) and `c2-05` (7). Design
results on so narrow a base are descriptive and are never reported as evaluation. Phase 1b
boundaries enter no Phase 2 cell.

*Seen before this amendment.* Beyond what Amendment 1 lists: the Phase 1b in-loop judge decisions
on the dev pools (`results/phase1b/analysis-unsealed.md`, DONE on all 23 Phase 1b dev not-done
boundaries); the failed requirement of each of the 24 dev not-done boundaries (`docs_updated` on
every `c2-01`, `manifest_correct` on every `c2-05`); the hidden checks behind those two
requirements; and the evidence-view prompt of one boundary of each task. No held-out content has
been read, and no repair-v1 or Phase 2 judge call has been made.

*Iterations.* At most three, as before. Each one replays `repair-v1:flash:evidence` over the
whole design set, 3 samples, on the Flash route of the Phase 2 design amendment, and reports
reliability, then item decisions (majority of 3) against primary truth, per source and truth
class. No other judge cell is called during design. The prompt names no task, file, function or
requirement from the design set; it is written as general instructions. Each iteration's prompt
is committed before its run, so its run manifest records the commit.

*Selection rule.* The frozen prompt is the iteration with the fewest false-DONE items on the
design set's natural not-done and blocked boundaries, among iterations whose false-CONTINUE on
natural done boundaries is at most 5%. Ties go to fewer pilot false-DONE items, then to the later
iteration. If no iteration meets the 5% bound, the one with the lowest natural false-CONTINUE is
frozen. Design may stop before three iterations; the rule then applies to the iterations run.

*Guard.* `hjr replay` refuses a `repair-v1` variant on any held-out boundary until tag
`repair-freeze-v1` is an ancestor of HEAD.

*Spend.* Design calls count toward the $20 stop on paid Phase 2 calls. At the pilot's measured
Flash cost an iteration is about $1.
