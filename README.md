# hermes-judge-audit

**Hermes' `/goal` judge grades the agent's report, not the work.**

At [`ffc74885`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py) the judge sees the goal and the first 4,000
characters of the agent's last message. No tool output, no workspace, and by default the same
model that did the work. So when the agent says it's done and is wrong, nothing the judge sees
says otherwise, and no judge model can catch it. I ran 30 sandboxed tasks through the real
`/goal` loop, with hidden per-requirement state verifiers as truth, to measure what that costs,
what the judge does when the evidence is in its input, and whether a judge-side fix holds up on
held-out data. Hypotheses and analysis rules were fixed in advance in
[`configs/prereg.md`](configs/prereg.md).

**Report: [`reports/report.md`](reports/report.md)**

- **It passed every unfinished task the agent called finished.** Of 178 natural endpoints from
  two agents, 9 were not done (4 weak, 5 strong), and all 9 final messages opened by saying they
  were. Every production-prompt cell judged all 9 DONE. They come from 2 tasks (weak) and 3
  (strong), so read them as counts, not rates. Blocked agents say so, and no cell judged any of
  the 12 blocked endpoints per arm DONE. In an enriched Phase 1b sample (weak arm, picked for
  failures, so not a rate), the in-loop judge passed 44 of 45 not-done endpoints.
- **It misses breakage it can see.** On constructed dev pairs where tool output in its input
  showed a broken required file, the production prompt still said DONE 7/7 (weak agent) and 2/2
  (strong). A paragraph appended to the message reporting an error flipped 0 of 12 decisions per
  arm. An instruction to check the evidence (`repair-v1`) caught 3/7 and 1/2, and on natural
  endpoints held back up to 5 finished tasks per arm. On natural endpoints, tool output alone
  removed no false DONE.
- **A stronger judge doesn't help, as the input predicts.** The agent's own model, Gemini 3 Flash
  Preview and GPT-6.1 Sol made the same false-DONE decisions (Sol ran through the Codex CLI, so
  harness differs too).
- **The truncation is backwards from the docs.** `_truncate` keeps the head; `goals.md` says
  "last ~4 KB". A caveat past the cut goes unseen, and head+tail moves the blind spot to the
  middle. Constructed inputs only: no natural message passed 2,757 characters.
- **Truth is audited.** The verifier caught 260 of 260 mutants, and a blind human review of 49
  endpoints found 0 endpoint-label errors (one requirement-level error, label unaffected).

Pre-registered tests, reported as run: H1 not supported (point estimates point the other way;
intervals reach 0), H4 not met (underpowered, as the power note said before any call), H6 not
established (2 tasks per arm; the test needs 5). Measured paid spend: $13.36 (judge calls $7.18,
Phase 1b $4.54, pilot $1.65; [breakdown](docs/methods.md#cost)).

## What this means for Hermes

- **Read DONE as "the agent says it's done".** The judge checks the report. When the agent is
  wrong about its own work, the judge has nothing to go on.
- **Fix the truncation mismatch.** Either the docs say "first ~4 KB" or the code keeps the tail,
  and the pilot says head plus tail isn't enough on its own. The head-only cut was already
  reported upstream in [issue #70699](https://github.com/NousResearch/hermes-agent/issues/70699)
  and [PR #70701](https://github.com/NousResearch/hermes-agent/pull/70701).
- **Check state, not the message.** Run the task's own checks, or ask for evidence the agent can
  only produce by doing the work. Hermes'
  [quality gates](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/website/docs/user-guide/features/goals.md#L135)
  run shell checks before the judge; no trial here configured one, so this is untested.

## Results

The report has every number. Full tables, all rebuilt without model calls:

| Stage | What | Tables |
|---|---|---|
| Pilot | 48 constructed items, 3 judge models | [`results/runs/pilot-v1/summary.md`](results/runs/pilot-v1/summary.md) |
| Phase 2 | 178 natural endpoints, 6 judge cells, 3 samples each | [`results/runs/phase2/summary.md`](results/runs/phase2/summary.md), unfixed verifier: [`summary-v1.md`](results/runs/phase2/summary-v1.md) |
| Phase 1b | 506 weak-arm endpoints, enriched sample | [`results/phase1b/analysis.md`](results/phase1b/analysis.md) |
| Human audit | 49 endpoints, blind | [`results/audit/report.md`](results/audit/report.md) |
| `repair-v1` design | 3 iterations, dev only | [`results/repair/`](results/repair/) |
| Controlled pairs | dev endpoints, constructed inputs | [`summary-weak.md`](results/runs/pairs/summary-weak.md), [`summary-strong.md`](results/runs/pairs/summary-strong.md) |

Methods, deviations, exclusions and spend: [`docs/methods.md`](docs/methods.md).

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

## Reproducing: the pilot

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

## Reproducing: trajectories

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
trials, six turns each, run past any production stop. Real tasks almost always end in turn 1
(every Phase 1a trial did, and 496 of 501 Phase 1b trials), so a soak-only workload supplies the
long resumed sessions the gate requires. It releases its evidence one stage per turn, and `ingest`
refuses it.

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
| `docs/` | Report methods, spend and logistics (`methods.md`), Harbor notes |
| `results/runs/` | Per-run verdicts, attempts, incidents, summaries and manifests |
| `results/oracle/`, `results/soak/` | Oracle and soak-gate reports |
| `results/phase1/`, `results/phase1b/` | Phase 1 run notes; Phase 1b notes, deviations and stage reports |
| `results/mutants/`, `results/regrade/` | Mutation-suite runs and regrade reports |
| `results/repair/` | `repair-v1` design iteration reports and error families |
| `results/smoke/` | Harness smoke check of the frozen suite (never ingested) |
| `third_party/hermes-agent/` | Hermes, a git submodule pinned at `ffc74885` |
