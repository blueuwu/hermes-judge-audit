# hermes-judge-audit

How often does Hermes Agent's `/goal` completion judge say a goal is done when the
environment shows it is not?

This repository audits the production judge in
[`hermes_cli/goals.py`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py)
against deterministic state verifiers and human labels, then measures judge-side repairs on a
frozen held-out set. Hypotheses and analysis rules are fixed in
[`configs/prereg.md`](configs/prereg.md).

Work in progress. Findings will lead this README once they exist.

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

## Layout

| Path | Contents |
|---|---|
| `hjr/judge.py` | Prompt construction, response views, verdict parsing and format violations |
| `hjr/arms.py` | Arm identity, sub-arms and the pooling guard |
| `hjr/replay.py`, `hjr/client.py`, `hjr/ratelimit.py` | Resume-safe replay with per-endpoint rate limits and logged retries |
| `hjr/metrics.py` | Reliability rates and semantic, effective and strict accuracy |
| `hjr/drift.py` | Judge-model drift on frozen items |
| `hjr/soak.py` | Soak compatibility gate evaluation |
| `hjr/schemas.py` | Pydantic records for every JSONL file |
| `hjr/pilot/` | Pilot items, format probes and summary tables |
| `configs/` | Pre-registration, judge arms, soak gate, seeds |
| `data/frozen/` | Frozen decision points |
| `results/runs/` | Per-run verdicts, attempts, incidents, summaries and manifests |
