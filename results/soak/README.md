# Soak results

Gate: `configs/soak_gate.toml`. Protocol: the soak amendments of 2026-10-01 in
`configs/prereg.md`. Each `soak-<arm>-<n>.json` is the output of `hjr soak`. Each
`.manifest.json` records the code, Hermes, lockfile, gate and task hashes and Harbor's
per-trial outcomes. Full job directories ship as release assets.

## Runs

| Report | Workload | Gate | Notes |
|---|---|---|---|
| `soak-weak-1.json` | M1 tasks only | FAIL | Measured under the original definitions, kept as recorded. Its 4 `rate_limited` were false positives from the old 429 pattern, and its context figures exclude tool schemas. Both were corrected before run 2. |
| `soak-strong-1.json` | M1 tasks only | FAIL | Both M1 tasks end in turn 1, so resumed context stays near 17–20k. This coverage gap motivated the workload amendment. |
| `soak-weak-2.json` | M1 tasks + `s0-01-incident-review` | **FAIL** | 13 unrecovered `tool_call_as_text` events. |
| `soak-strong-2.json` | M1 tasks + `s0-01-incident-review` | **PASS** | |
| `soak-weak-3.json` | M1 tasks + `s0-01-incident-review` | **FAIL** | Weak arm moved to SiliconFlow by amendment. 1 unrecovered `tool_call_as_text` event. |
| `soak-weak-4.json` | M1 tasks + `s0-01-incident-review` | **PASS** | Weak arm replaced by GLM-5.3-Flash on Z.AI by amendment. |

Runs 2–4 used the frozen workload (`b50a3e1`) with harness code at `00a6bf4`. Run 3 differs only in the weak
arm's provider (`1eed5ed`), run 4 only in the weak arm's model and provider (`95bb700`). Other later commits change only reporting. All runs used the same settings: `-k 3 -n 6`, six turns, `soak=true`, request
dumps on, and no per-arm tuning.

## Run 2 by arm and task

Context is the estimated prompt size, in tokens, at the turn-5 and turn-6 requests (one
value per trial).

| Arm | Task | Trials × turns | Tool calls | Events | Resumes | 429s | Infra failures | Context t5 | Context t6 |
|---|---|---|---|---|---|---|---|---|---|
| weak (Qwen3-Coder 30B, Alibaba) | c1-01 (M1) | 3 × 6 | 25 | 0 | 15/15 | 0 | 0 | 17.4k, 17.7k, 22.4k | 17.7k, 18.0k, 22.8k |
| | c3-02 (M1) | 3 × 6 | 30 | 0 | 15/15 | 0 | 0 | 17.8k, 18.3k, 18.3k | 18.0k, 18.4k, 18.5k |
| | s0-01 (soak only) | 3 × 6 | 50 | 13 `tool_call_as_text` | 15/15 | 0 | 0 | 15.5k, 15.5k, 50.1k | 15.9k, 15.9k, 55.9k |
| strong (DeepSeek V4.1 Flash, DeepSeek) | c1-01 (M1) | 3 × 6 | 17 | 0 | 15/15 | 0 | 0 | 16.6k, 17.4k, 18.3k | 16.9k, 18.1k, 18.6k |
| | c3-02 (M1) | 3 × 6 | 32 | 0 | 15/15 | 0 | 0 | 17.7k, 18.0k, 18.9k | 17.9k, 18.3k, 19.1k |
| | s0-01 (soak only) | 3 × 6 | 118 | 0 | 15/15 | 0 | 0 | 41.9k, 43.6k, 45.4k | 47.4k, 47.4k, 51.8k |

Both arms reached a peak of 6 agent requests in flight. Harbor recorded no errored trials and no
retries, and no failed turns were recorded.

Gate outcomes over the full gate task list:

- **weak: FAIL.** 13 unrecovered events, against a threshold of 0. All other criteria pass.
- **strong: PASS.** Peak resumed context was 51.8k, inside [30k, 60k].

The same gate applied to the M1 tasks alone fails for both arms on coverage only: resumed
context is at most 22.8k, and peak concurrency within the M1 trials is 4. This is informational,
as the amendment specifies.

## `reasoning_content` round trip

The check compared every request body Hermes dumped against the stored history.

| Arm | Hermes policy | Requests | Resumed | Assistant messages checked | Result |
|---|---|---|---|---|---|
| weak (run 2, Alibaba) | strip | 159 | 113 | 2087 | PASS: field never sent |
| weak (run 3, SiliconFlow) | strip | 262 | 176 | 4735 | PASS: field never sent |
| weak (run 4, GLM-5.3-Flash, Z.AI) | strip | 161 | 116 | 1840 | PASS: field never sent |
| strong | replay | 179 | 127 | 2199 | PASS: 1989 identical, 210 padded |

For DeepSeek, every assistant message in every resumed request carried its stored
`reasoning_content` verbatim. Messages stored without reasoning (failed-turn notices, and
turns with no reasoning) carried Hermes's `" "` pad. Totals: 0 missing, 0 rewritten, 0
unaligned with stored tool-call ids, 0 stored values changed between turns, and 0 error dumps.
No resumed request was rejected.

## The weak-arm failure in run 2

All 13 events are in `s0-01` and share one form. Instead of making a tool call, Qwen wrote its
native XML call syntax as message text. The text has no `<tool_call>` wrapper and no closing
`</function>`:

```
Let me first check what evidence stages are available.

<function=search_files>
<parameter=pattern>
^/app/evidence/
</parameter>
...
```

The response arrives with `finish_reason=stop` and no structured tool calls. Hermes at
`ffc74885` has no text tool-call fallback, so it treats the message as the turn's final answer
and runs nothing. Hermes's own evals flag this output as `raw_xml_noise`
(`evals/core_tool_deferral/worker.py`).

- It happened on the first assistant message of all three `s0-01` trials, at about 13.8k
  context. It is therefore not a long-context effect. The validation trial opened with the same
  sentence and made a structured call, so whether it occurs on turn 1 is stochastic.
- One trial (`HDzfwkQ`) made structured calls from turn 2 onward and reached 50.1k/55.9k
  context.
- In the other two (`LEjGnkT`, `wYBGx3R`), every later turn repeated the pattern, once per turn.
  The text calls in the history appear to be copied, so nothing ran in six turns, context stayed
  near 15k, and the task score was 0.
- None of the six M1 trials showed it.

This is a genuine protocol failure of the weak arm on its pinned route, not a harness or
infrastructure fault. The harness recorded no failed turns, every resume was accepted, and the
strong arm passed the same workload. The weak arm does not proceed to Phase 1 as configured.
Any change of model or route must be made by dated amendment and soaked again.

## Run 3: weak arm on SiliconFlow

The weak arm was moved from Alibaba to SiliconFlow (fp8, the official Qwen checkpoint precision)
by the amendment of 2026-10-01 in `configs/prereg.md`, committed before the run. Gate, tasks,
workload and settings were unchanged.

| Task | Trials × turns | Tool calls | Events | Resumes | 429s | Infra failures | Context t5 | Context t6 |
|---|---|---|---|---|---|---|---|---|
| c1-01 (M1) | 3 × 6 | 34 | 0 | 15/15 | 0 | 0 | 18.5k, 18.9k, 21.2k | 19.2k, 19.2k, 21.6k |
| c3-02 (M1) | 3 × 6 | 31 | 0 | 15/15 | 0 | 0 | 17.4k, 18.8k, 20.0k | 17.6k, 19.0k, 20.7k |
| s0-01 (soak only) | 3 × 6 | 144 | 1 `tool_call_as_text` | 15/15 | 0 | 0 | 42.1k, 50.6k, 51.0k | 46.7k, 55.4k, 57.3k |

Peak in-flight was 6. Harbor recorded no errored trials and no retries, and no failed turns were
recorded. The `reasoning_content` check passed: 262 requests (176 resumed) and 4735 assistant
messages, none carrying the field.

**Gate: FAIL**, on 1 unrecovered event against a threshold of 0. Every other criterion passes,
including coverage: all three `s0-01` trials made structured calls throughout and reached
42–57k resumed context.

The event is in `s0-01` trial `egHoNyz`, turn 6, a normal turn (not `past_stop`). The final
answer is a complete prose summary of the report, followed by one line of text:

```
<function=terminate>
```

There is no `terminate` tool among the 23 Hermes offered, the call carries no parameters, and it
was the trial's last message, so nothing was left stalled. It is still Qwen's native call syntax
in the content of a message with no structured calls, which is exactly what the frozen detector
counts, and the gate has no exception for it.

Reading against run 2:

- The stalling failure did not recur. On Alibaba, 2 of 3 `s0-01` trials made no structured call
  for six turns; on SiliconFlow, none did. The provider's parsing evidently mattered for that.
- Qwen3-Coder still emits its XML call syntax as text on SiliconFlow, at a much lower rate. As
  the amendment fixed in advance, this residual is attributed to the model, not the route, and
  no third route is tried. The weak arm stays blocked from Phase 1 pending a further amendment.

## Run 4: weak arm on GLM-5.3-Flash

Qwen3-Coder was replaced as the weak arm by GLM-5.3-Flash, pinned to Z.AI's own endpoint (fp8),
by the amendment of 2026-10-02 in `configs/prereg.md`, committed before the run. Gate, tasks,
workload and settings were unchanged.

| Task | Trials × turns | Tool calls | Events | Resumes | 429s | Infra failures | Context t5 | Context t6 |
|---|---|---|---|---|---|---|---|---|
| c1-01 (M1) | 3 × 6 | 13 | 0 | 15/15 | 0 | 0 | 16.2k, 16.3k, 16.4k | 16.5k, 16.5k, 16.7k |
| c3-02 (M1) | 3 × 6 | 15 | 0 | 15/15 | 0 | 0 | 15.8k, 16.1k, 16.8k | 16.0k, 16.3k, 16.9k |
| s0-01 (soak only) | 3 × 6 | 93 | 0 | 15/15 | 0 | 0 | 30.6k, 31.8k, 37.7k | 32.6k, 35.7k, 40.7k |

**Gate: PASS.** 121 structured tool calls with no protocol events of any kind, 45/45 resumes,
peak in-flight 6, no 429s, no failed turns, and no errored trials or retries in Harbor. The
`reasoning_content` check passed: 161 requests (116 resumed) and 1840 assistant messages, none
carrying the field. The run took 11 minutes.

Coverage passes with less margin than the other arms. GLM reads more selectively than Qwen or
DeepSeek: 93 workload calls against 144 and 118, and resumed context of 30.6–40.7k against a
30k floor. The lowest turn-5 value, 30.6k, is 2% above it. As for the strong arm, the M1-only
sub-report fails on coverage (28 calls, 16.9k context, 4 in flight), which is the gap the
workload exists to fill; it is not a gate criterion.

With both arms through the gate, Phase 1 can start on GLM-5.3-Flash and DeepSeek V4.1 Flash.

## Separation from the evaluation

- **M1 behaviour:** unchanged by the amendments. All 24 M1 trials in runs 2–4 were free of
  events and had every resume accepted. Their task scores are in the manifests, but soak scores
  are not results.
- **Infrastructure soak coverage:** comes from `s0-01`, a soak-only task. It reached 30.6k–57.3k
  resumed context with 6 requests in flight and no 429s.
- **Model evaluation:** unaffected. `s0-01` is `soak_only`, `ingest` refuses it, and no soak
  trial or boundary enters any analysis.
