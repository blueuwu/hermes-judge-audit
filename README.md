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

```bash
cp .env.example .env            # add OPENROUTER_API_KEY
uv run hjr pilot-build          # regenerates data/frozen/pilot_boundaries.jsonl (committed)
uv run hjr replay --boundaries data/frozen/pilot_boundaries.jsonl --run-id pilot-v1 \
  --samples 5 \
  --variant prod-plain:flash:head4k     --variant prod-plain:flash:headtail4k \
  --variant prod-plain:self-weak:head4k --variant prod-plain:self-weak:headtail4k
uv run hjr pilot-summary --run-id pilot-v1
```

The replay is resume-safe: rerunning it only fills in missing samples. Each run writes verdicts,
errors and a manifest (code, Hermes and lockfile versions, input hashes, pinned providers) under
`results/runs/<run_id>/`.

## Layout

| Path | Contents |
|---|---|
| `hjr/judge.py` | Prompt construction, response views, verdict parsing |
| `hjr/replay.py`, `hjr/client.py` | Resume-safe replay over OpenAI-compatible endpoints |
| `hjr/schemas.py` | Pydantic records for every JSONL file |
| `hjr/pilot/` | Pilot item construction and summary tables |
| `configs/` | Pre-registration, judge models, seeds |
| `data/frozen/` | Frozen decision points |
| `results/runs/` | Per-run verdicts, summaries and manifests |
