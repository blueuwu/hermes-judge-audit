# hermes-judge-audit

How often does Hermes Agent's `/goal` completion judge say a goal is done when the
environment shows it is not?

This repository audits the production judge in
[`hermes_cli/goals.py`](https://github.com/NousResearch/hermes-agent/blob/ffc74885c5f6eb75f6c134fb4eef86d734066623/hermes_cli/goals.py)
against deterministic state verifiers and human labels, then measures judge-side repairs on a
frozen held-out set.

Work in progress. Findings will lead this README once they exist.

## Setup

```bash
uv sync
uv run pytest
```
