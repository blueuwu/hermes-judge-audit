# hermes-judge-audit

How often does Hermes Agent's `/goal` completion judge say a goal is done when the
environment shows it is not?

This repository audits the production judge in
[`hermes_cli/goals.py`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py)
against deterministic state verifiers and human labels, then measures judge-side repairs on a
frozen held-out set. Hypotheses and analysis rules are fixed in
[`configs/prereg.md`](configs/prereg.md).

Status: offline pilot done; agent harness (M1) in progress.

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
uv run harbor run -p tasks/ -e docker --ek "$EK" -k 3 -n 6 -o jobs --job-name soak-<arm>   --agent-import-path hjr.harness.agent:HermesGoalLoop --ak arm=<arm> --ak soak=true
uv run hjr soak --job jobs/soak-<arm> --out results/soak/soak-<arm>.json
```

| Task | Category | What can go wrong |
|---|---|---|
| `c1-01-csv-to-json` | C1 control | Quoted fields with commas; amounts as strings; input edited |
| `c3-02-missing-sqlite` | C3 tool friction | `bin/migrate.sh` needs a `sqlite3` CLI that is not installed; partial migrations |
| `s0-01-incident-review` | Soak only, never analysed | Six-stage incident investigation; long resumed sessions with heavy tool use |

## Layout

| Path | Contents |
|---|---|
| `hjr/judge.py` | Prompt construction, response views, verdict parsing and format violations |
| `hjr/arms.py` | Arm identity, sub-arms and the pooling guard |
| `hjr/replay.py`, `hjr/client.py`, `hjr/ratelimit.py` | Resume-safe replay with per-endpoint rate limits and logged retries |
| `hjr/metrics.py` | Reliability rates and semantic, effective and strict accuracy |
| `hjr/drift.py` | Judge-model drift on frozen items |
| `hjr/soak.py`, `hjr/soakreport.py` | Soak gate evaluation, and soak reports built from Harbor trials |
| `hjr/goalloop.py`, `hjr/harness/` | The `/goal` loop as Hermes runs it, and the Harbor agent that drives it |
| `hjr/ingest.py` | Harbor job to `BoundaryRecord`s, with exclusions listed |
| `harness/` | Hermes base image and the shared verifier entry point |
| `tasks/` | Harbor tasks: goal, workspace, oracle and hidden state checks |
| `hjr/schemas.py` | Pydantic records for every JSONL file |
| `hjr/pilot/` | Pilot items, format probes and summary tables |
| `configs/` | Pre-registration, judge arms, soak gate, seeds |
| `data/frozen/` | Frozen decision points |
| `results/runs/` | Per-run verdicts, attempts, incidents, summaries and manifests |
