# hermes-judge-audit

How often does Hermes Agent's `/goal` completion judge say a goal is done when the
environment shows it is not?

This repository audits the production judge in
[`hermes_cli/goals.py`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py)
against deterministic state verifiers and human labels, then measures judge-side repairs on a
frozen held-out set. Hypotheses and analysis rules are fixed in
[`configs/prereg.md`](configs/prereg.md).

Status: Phase 1a trajectories frozen (178 boundaries), primary verifier frozen after the mutation suite, Phase 1b enrichment and `repair-v1` design done (tag `repair-freeze-v1`). Phase 2 replay done and analysed (below). Human verifier audit done (no endpoint label errors, one requirement-level error in 49 audited). Controlled counterfactual pairs run on dev boundaries (below). Report: [`reports/report.md`](reports/report.md).

## Pilot findings (M0.5, constructed items)

48 hand-built decision points, 5 samples each, production prompt and sampling, three judge
models. These are attack-success rates on constructed inputs, not natural-trajectory estimates.
Full tables: [`results/runs/pilot-v1/summary.md`](results/runs/pilot-v1/summary.md).

| Judged done (majority of 5), production `head4k` view | Gemini 3 Flash Preview | Qwen3-Coder 30B (self) | Gemini 3.8 Flash |
|---|---|---|---|
| Done controls and hedged/terse done reports (12 items) | 12/12 | 12/12 | 12/12 |
| A1: confident claim of work that was not done | 4/4 | 4/4 | 4/4 |
| A4: checklist with one requirement silently missing | 0/4 | 4/4 | 0/4 |
| A6: instruction to the judge echoed from the workspace | 0/4 | 1/4 | 0/4 |
| Long reports with no caveat (done) | 4/4 | 4/4 | 3/4 |
| Unmet requirement stated at ~1k chars | 0/4 | 1/4 | 1/4 |
| Unmet requirement stated at ~4.5k / ~8k chars | 4/4, 4/4 | 4/4, 4/4 | 3/4, 3/4 |
| False-DONE over all not-done calls | 60/160 | 94/160 | 53/160 |

- **The judge believes the report.** Every model accepted every confident false claim; the
  production prompt counts an explicit confirmation as completion.
- **The judge reads only the first 4,000 characters** (`_truncate` keeps the head, while
  `goals.md:185` says "last ~4 KB"). A caveat past that point is invisible, and the item is
  judged done.
- **Head+tail is not a fix by itself.** Keeping the first and last 2,000 characters recovers the
  ~8k caveat for Flash Preview (0/4 judged done) but loses the ~3.5k one, which now falls in the
  cut middle (4/4 judged done).
- **No format problems.** 0 parse failures and 0 format violations in 1,440 pilot calls and 60
  format probes, so fail-open did not hide any errors here.
- **Drift.** Preview → 3.8 Flash changed 9.6% of decisions, all on truncation items; correctness
  shows no detectable difference at n = 48 (exact McNemar p = 1). 3.8 Flash reasons by default,
  so this measures the model and its default together.

The pre-registered go rule was met on both effects. Measured spend: $1.65 for the 1,440 pilot calls.

## Phase 2 results (natural trajectories)

178 Phase 1a boundaries (weak 88, strong 90), six judge cells, 3 samples each. Truth is the
frozen primary verifier (weak 72 done, 4 not done, 12 blocked; strong 73 done, 5 not done,
12 blocked). Item decision is the majority of 3. Arms are reported separately and never pooled.
Full tables: [`results/runs/phase2/summary.md`](results/runs/phase2/summary.md); with truth as
frozen at Phase 1: [`summary-v1.md`](results/runs/phase2/summary-v1.md).

| Production self judge, `prod-plain:self:head4k` | weak (GLM-5.3-Flash) | strong (DeepSeek V4.1 Flash) |
|---|---|---|
| Semantic accuracy (calls) | 249/262 (95.0%) | 255/270 (94.4%) |
| False-DONE (items, truth ≠ done) | 4/16 | 5/17 |
| False-CONTINUE (items, truth = done) | 0/72 (Wilson 0.0–5.1%) | 0/73 (Wilson 0.0–5.0%) |
| FD − FC, task-bootstrap 95% interval | +25.0 pp (0.0 to 68.4) | +29.4 pp (0.0 to 70.0) |
| Unanimous items across 3 samples | 85/88 | 90/90 |

- **H1 not supported.** It needs the FD − FC interval below 0. In both arms the point estimate is
  positive and the interval reaches 0 from above.
- **H2 (descriptive).** Every false-DONE item, in every cell, is on a C2, C4 or C6 task. No cell
  judges any of the 12 blocked C5 boundaries done, in either arm. C1 and C3 have no truth ≠ done
  boundaries, so the comparison against controls that H2 names cannot be made.
- **H3 not tested.** Phase 1 has no G-contract boundaries (Phase 2 design amendment).
- **H4 not met** in any of its four tests (2 arms × {flash, strong}). Each has n = 10 held-out
  truth ≠ done boundaries and at most 1 discordant pair, against the 15 required. This is the
  "no detectable difference at n = 10" the prereg stated in advance. False-CONTINUE on the
  44 held-out done items per arm rises by 0 to +6.8 pp (at most 3 discordant pairs). Every
  comparison reads "no detectable difference".
- **H5 (exploratory).** Item correctness of self against Flash, and of either against strong,
  differs by at most 2 items in 88 or 90 (all "no detectable difference"). At the cell level,
  Flash matches the self judge's false-DONE in both arms. Strong matches it too, and adds 1 (weak)
  and 2 (strong) false-CONTINUE items.
- **Evidence view and repair-v1.** `prod-plain:flash:evidence` has the same false-DONE as
  `flash:head4k` in both arms. `repair-v1` lowers false-DONE by 1 item in the strong arm only.
  Against the `prod-plain` cell of the same model, it raises false-CONTINUE by 0 to 4 items.
  The highest count is under `repair-v1:strong:evidence` (5/72 weak, 5/73 strong).
- **Truth sensitivity.** Truth as frozen at Phase 1 counts seven more boundaries as not done (five
  `c2-01`, two `c6-04`, see the frozen-verifier note). Under it the self judge's false-DONE is
  7/19 (weak) and 9/21 (strong). The strong arm's FD − FC interval then excludes 0
  (+42.9 pp, 6.2 to 80.0).
- **Reliability.** No cell has an unresolved call. There are 2 parse failures in 264 calls
  (`self-weak`) and 0 format violations anywhere. Transport errors per attempt:
  - `strong` (Codex CLI) head4k: 139/403 (weak) and 120/390 (strong). These are the known hangs,
    each retried to success.
  - `flash:head4k`, weak arm: 129/393.
  - Every other cell: 16 or fewer.
- **Strong harness check.** The Codex CLI and paid-API harnesses agree on 9/10 and 9/10 items in
  the strong arm, and 10/10 and 10/10 in the weak arm.
  - Limitation, applying to every strong result above: the strong and Flash cells differ in
    harness as well as model, and only this 20-boundary check bounds the harness effect.
  - The strong cells are labelled "GPT-6.1 Sol via Codex CLI; harness prompt and sampling params
    not controllable".
- **Not exercised.** No Phase 1 response reaches 4,000 characters. So the truncation effect from
  the pilot does not occur here. `headtail4k` is identical to `head4k` by construction, and was
  not called.
- **Small sample.** The 16 (weak) and 17 (strong) truth ≠ done boundaries come from few tasks.
  These are counts from a small natural sample, not precise rates.

Measured spend on paid Phase 2 calls, including the repair design and the controlled pairs:
$7.18 of the $20 stop. The 1,315 Codex CLI calls are unbilled ([`results/runs/phase2/spend.md`](results/runs/phase2/spend.md)).

- **Human verifier audit.** The owner audited 49 boundaries blind, without the judge verdict or
  the stratum ([`results/audit/report.md`](results/audit/report.md)). As the prereg sets out, the
  strata are formed over the 178 Phase 1a boundaries of both arms. It found no endpoint label
  errors, and one requirement-level error in 49 audited.

  | Stratum | Population | Audited | Endpoint label errors | Wilson 95% |
  |---|---:|---:|---:|---|
  | A, verifier and judge disagree | 9 | 9 | 0 | 0 to 29.9% |
  | B, both say DONE | 145 | 30 | 0 | 0 to 11.4% |
  | C, both say not DONE | 24 | 10 | 0 | 0 to 27.8% |

  - Counted as the prereg's verifier error rate, which includes requirement-level errors,
    stratum C has 1 of 10 (Wilson 1.8 to 40.4%), as in the audit report.
  - The one requirement-level error is in a `c5-03` (missing package) boundary from the weak
    arm. The agent pinned an available substitute, and its tests passed in its own environment.
    The verifier's `tests_pass` check failed, by the auditor's reading because its image lacks
    the agent's installed packages. The boundary is still correctly `blocked`, because the
    requested package is infeasible to install.
  - The error is recorded as a known limitation, and the verifier is not fixed (owner's decision,
    2026-10-13). A fix would change no truth label, so there is no sensitivity rerun under the
    prereg's *Truth* rules.

## Controlled pairs (dev boundaries, constructed inputs)

Dev boundaries only, arms never pooled, decisions are the majority of 3 samples. Rules are the
prereg's *Controlled counterfactual pairs* and its note of 2026-10-14: H6 is the only confirmatory
test, E1, H8 and the repair comparisons are descriptive. Full tables:
[`results/runs/pairs/summary-weak.md`](results/runs/pairs/summary-weak.md),
[`summary-strong.md`](results/runs/pairs/summary-strong.md); inputs and build counts:
[`data/pairs/README.md`](data/pairs/README.md).

| `prod-plain:flash` unless noted | weak (GLM-5.3-Flash) | strong (DeepSeek V4.1 Flash) |
|---|---|---|
| Identical-input flips, `head4k` (noise floor) | 0/34 (Wilson 0 to 10.2%) | 0/36 (Wilson 0 to 9.6%) |
| H6 pairs: flips with the caveat before / after the 4,000-character cut | 2/34 / 0/34 | 4/36 / 0/36 |
| H6 exact sign-flip test, per-task differences | p = 0.25 (2/2 tasks positive) | p = 0.25 (2/2 tasks positive) |
| Edit flips per family (hedging, error, paraphrase, tone), exact 95% CI | 0/12 each (0 to 26.5%) | 0/12 each (0 to 26.5%) |
| Evidence-visible state pairs, mutated arm not DONE: `prod-plain:flash:evidence` | 0/7 | 0/2 |
| same, `repair-v1:flash:evidence` | 3/7 | 1/2 |
| same, `repair-v1:strong:evidence` (Codex CLI) | 3/7 | 1/2 |

- **H6 not established** in either arm. A caveat placed before the cut changed the decision on 2
  (weak) and 4 (strong) pairs, and the same caveat after the cut on none. But the flips sit in only
  2 tasks per arm (weak `c2-01`, `c6-03`; strong 3 of 3 pairs on `c2-05`, and `c6-04`). The exact
  test needs at least 5 tasks with a difference, so p = 0.25 in both arms.
- **E1 (descriptive).** `paraphrase` and `tone` edits flipped no decision in 12 bases per arm,
  against 0 identical-input flips on the same bases. With 12 bases the exact upper bound is 26.5%,
  so no family is called inert. The 10-point reference tolerance is recorded for later runs.
- **Hedging and error (descriptive).** No flips either. In each arm 10 of the 12 bases are judged
  DONE, and stay DONE after an inserted hedge or a separate paragraph reporting an error. The
  judge's decision did not respond to an explicit error report appended to a DONE account.
- **H8 (descriptive).** On evidence-visible state pairs, where one required file or record was
  mutated after the run and the replayed tool output shows it, `prod-plain:flash:evidence` judged
  the mutated arm DONE in every pair (0/7, 0/2). Both `repair-v1` cells caught 3/7 and 1/2. The
  smallest McNemar p is 0.25 (weak) and 1.0 (strong), 1.0 after Holm, so these are counts, not a
  detected difference. 8 weak and 6 strong state pairs were evidence-invisible and are excluded.
  Weak-arm `prod-plain` H8 had no discordant pairs and entered Holm at p = 1 per the prereg's
  k = 5 (strong-arm `prod-plain` H8 likewise, 0 of 2).
- **H7 not run.** No dev not-done base has a claim-free account.
- **Limits.** These are dev pilot numbers on 12 tasks per arm. A confirmatory pairs run needs
  held-out boundaries and its own amendment. State pairs cover only boundaries whose last three
  calls replay, which favours simple, deterministic endings. Replay is checked on the stored
  output tails only (the last 500 characters): a replay that printed extra text before the same
  tail would pass, and a timing-only difference fails when the cut moves with a timing value's
  width or lands inside a timing field, which excludes the pair.

Spend: 1,752 billed calls, $1.72, bringing paid Phase 2 calls to $7.18 of the $20 stop; the
207 Codex CLI calls are unbilled. Every call parsed.

## Setup

```bash
git clone --recurse-submodules <this repo>
cd hermes-judge-audit
uv sync
uv run pytest
```

Hermes is vendored as a git submodule at the audited commit (`third_party/hermes-agent`). The
replay imports the judge prompts, truncation and verdict parser from it directly, and
`tests/test_judge_parity.py` checks that every replayed prompt is byte-identical to what
`judge_goal` sends. On Windows, enable long paths before cloning (`git config --global
core.longpaths true`); the Hermes docs tree has deep paths.

## Offline judge pilot

48 constructed decision points with truth fixed by design: self-report attacks, controls in both
directions, and a truncation dose-response set where one caveat sits at ~1k, ~3.5k, ~4.5k or ~8k
characters into a long report.

Run order: check the pinned routes, probe each judge's output format, then the pilot (Flash
Preview cells first, so its outputs are frozen early), then the drift comparison.

```bash
cp .env.example .env            # add OPENROUTER_API_KEY
uv run hjr check-route          # pinned models and providers still listed (metadata only)

uv run hjr replay --boundaries data/frozen/format_probe.jsonl --run-id probe-v1 --samples 1 \
  --variant prod-plain:flash:head4k --variant prod-plain:drift:head4k \
  --variant prod-plain:self-weak:head4k
uv run hjr probe-summary --run-id probe-v1

# Flash Preview first, so its outputs are frozen before anything else
uv run hjr replay --boundaries data/frozen/pilot_boundaries.jsonl --run-id pilot-v1 --samples 5 \
  --variant prod-plain:flash:head4k --variant prod-plain:flash:headtail4k
uv run hjr replay --boundaries data/frozen/pilot_boundaries.jsonl --run-id pilot-v1 --samples 5 \
  --variant prod-plain:self-weak:head4k --variant prod-plain:self-weak:headtail4k \
  --variant prod-plain:drift:head4k --variant prod-plain:drift:headtail4k
uv run hjr pilot-summary --run-id pilot-v1
uv run hjr drift --run-id pilot-v1 --boundaries data/frozen/pilot_boundaries.jsonl \
  --baseline prod-plain:flash:head4k --candidate prod-plain:drift:head4k
uv run hjr cost --run-id pilot-v1 --calls 11000
```

Every call is recorded with one outcome (`parsed`, `parse_failed`, `format_violation`; transport
failures are logged per attempt and never become verdicts), its raw response, the
provider-reported model and provider, finish reason, tokens and billed cost. Analysis refuses
to pool records from different arms or sub-arms, and an arm stops at once if its reported
identity changes mid-run. `hjr reparse` re-parses stored raw responses without new calls. The
replay is resume-safe: rerunning it only fills in missing samples.

## Agent harness (M1)

Hermes runs inside Harbor under the `/goal` loop. `hjr.harness.agent:HermesGoalLoop` extends
Harbor's Hermes agent: Hermes is baked into `hjr/hermes-base` at the audited commit (no
per-trial install from `main`), each turn is one `hermes chat --resume`, the workspace is
snapshotted at every turn boundary, and the production judge runs on the host with the replay
client. A separate verifier container grades the final workspace and every snapshot against
per-requirement checks that never enter the agent's image. The agent can reach only the model
endpoint and the verifier has no network. On Docker Desktop this needs WSL2 kernel 6.x and the
compose override in `harness/egress/`, which lets Harbor's egress sidecar resolve names through
Docker Desktop's DNS. Departures from an interactive `/goal` session are listed in the
pre-registration amendments.

```bash
docker build -t hjr/hermes-base:ffc74885 harness/base
uv sync --extra harness
export HJR_ROOT="$PWD"
EK='extra_docker_compose=["harness/egress/docker-desktop-dns.yaml"]'   # Docker Desktop only
uv run harbor run -p tasks/ -a oracle -e docker --ek "$EK"   # every task must score 1.0
uv run harbor run -p tasks/ -e docker --ek "$EK" -n 6 -o jobs --job-name <run> \
  --agent-import-path hjr.harness.agent:HermesGoalLoop --ak arm=weak
uv run hjr ingest --job jobs/<run> --out data/frozen/<run>.jsonl
```

Before Phase 1 each agent arm passes the soak gate (`configs/soak_gate.toml`): six concurrent
trials, six turns each, run past any production stop. Both M1 tasks end in turn 1, so a soak-only
workload supplies the long resumed sessions the gate requires. It releases its evidence one stage
per turn, and `ingest` refuses it.

```bash
uv run harbor run -p tasks/ -e docker --ek "$EK" -k 3 -n 6 -o jobs --job-name soak-<arm> \
  --agent-import-path hjr.harness.agent:HermesGoalLoop --ak arm=<arm> --ak soak=true
uv run hjr soak --job jobs/soak-<arm> --out results/soak/soak-<arm>.json
```

The task suite is 30 tasks in six categories, described in [`tasks/README.md`](tasks/README.md):
controls, multi-part goals, tool friction, verification-required tasks adapted from
Terminal-Bench 2.0, infeasible goals, and long reports that run past the judge's 4,000-character
view. Every task's oracle scores 1.0 (`results/oracle/`). A seeded, category-stratified split
(`configs/split.toml`, `hjr split`) puts 12 tasks in dev and 18 in held-out, and `ingest` takes
each boundary's split from it.

```bash
uv run harbor run -p tasks/ -e docker --ek "$EK" -x "s0-*" -k 3 -n 6 -o jobs --job-name phase1-<arm> \
  --agent-import-path hjr.harness.agent:HermesGoalLoop --ak arm=<arm>
uv run hjr ingest --job jobs/phase1-<arm> --out data/frozen/phase1-<arm>.jsonl
```

## Layout

| Path | Contents |
|---|---|
| `hjr/judge.py` | Prompt construction, response views, verdict parsing and format violations |
| `hjr/arms.py` | Arm identity, sub-arms and the pooling guard |
| `hjr/replay.py`, `hjr/client.py`, `hjr/ratelimit.py` | Resume-safe replay with per-endpoint rate limits and logged retries |
| `hjr/metrics.py` | Reliability rates and semantic, effective and strict accuracy |
| `hjr/drift.py` | Judge-model drift on frozen items |
| `hjr/phase2.py`, `hjr/analysis.py`, `hjr/stats.py` | Phase 2 plan, per-arm analysis, intervals and paired tests |
| `hjr/codex.py` | The `strong` judge through the Codex CLI: isolated calls, pinned model and version |
| `hjr/verifier.py` | Verifier versions (`data/verifiers.json`) and offline grading in each task's verifier image |
| `hjr/mutants/` | Verifier mutation suite (prereg Amendment 1): mutants per family, frozen in `data/mutants/suite.json` |
| `hjr/estimate.py` | Cost estimate per Phase 2 cell from measured token ratios and live prices |
| `hjr/soak.py`, `hjr/soakreport.py` | Soak gate evaluation, and soak reports built from Harbor trials |
| `hjr/goalloop.py`, `hjr/harness/` | The `/goal` loop as Hermes runs it, and the Harbor agent that drives it |
| `hjr/ingest.py`, `hjr/split.py` | Harbor job to `BoundaryRecord`s, with exclusions listed; the dev/held-out split |
| `harness/` | Hermes base image and the shared verifier entry point |
| `tasks/` | Harbor tasks: goal, workspace, oracle and hidden state checks ([`tasks/README.md`](tasks/README.md)) |
| `hjr/schemas.py` | Pydantic records for every JSONL file |
| `hjr/pilot/` | Pilot items, format probes and summary tables |
| `hjr/regrade.py` | Primary truth: the frozen boundaries regraded at the frozen primary verifier (`data/truth/`) |
| `hjr/audit.py` | Human verifier audit: seeded draw, blind view, records and report |
| `hjr/repair.py`, `hjr/repair_design.py` | The `repair-v1` prompt and its dev design iterations (Amendment 3) |
| `hjr/pairs.py`, `hjr/pairs_analysis.py` | Controlled counterfactual pairs: dev-only builder and summary tables |
| `hjr/enrichment.py`, `hjr/pools.py`, `hjr/preflight.py` | Phase 1b: Stage A/B selection, reported pools, launch checks |
| `hjr/routes.py` | Pinned-route check from public model metadata |
| `hjr/config.py`, `hjr/manifest.py`, `hjr/cli.py` | Config loading, run provenance and measured spend, and the `hjr` command |
| `configs/` | Pre-registration, judge arms, soak gate, seeds, task split |
| `data/frozen/` | Frozen decision points |
| `data/truth/` | Primary truth per frozen boundaries file (`hjr regrade`) |
| `data/mutants/` | Frozen mutation suite and the equivalent-mutant decisions |
| `data/labels/` | The retired labelling order (Amendment 1) |
| `docs/` | Report methods, spend and logistics (`methods.md`), Harbor notes, design drafts not yet adopted into the prereg |
| `results/runs/` | Per-run verdicts, attempts, incidents, summaries and manifests |
| `results/oracle/`, `results/soak/` | Oracle and soak-gate reports |
| `results/phase1/`, `results/phase1b/` | Phase 1 run notes; Phase 1b notes, deviations and stage reports |
| `results/mutants/`, `results/regrade/` | Mutation-suite runs and regrade reports |
| `results/repair/` | `repair-v1` design iteration reports and error families |
| `results/smoke/` | Harness smoke check of the frozen suite (never ingested) |
| `third_party/hermes-agent/` | Hermes, a git submodule pinned at `ffc74885` |
