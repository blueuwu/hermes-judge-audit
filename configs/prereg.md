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
