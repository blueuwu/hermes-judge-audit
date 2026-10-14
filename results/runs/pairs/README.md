# Controlled pairs summaries

`hjr pairs-summary` takes one items file and one verdicts file, so each arm's inputs were
concatenated first (read-only, outside the repository), then summarised with the 10-point
reference tolerance of the prereg note of 2026-10-14:

```bash
for a in weak strong; do
  cat data/pairs/response-$a.jsonl data/pairs/state-$a.jsonl > items-$a.jsonl
  cat results/runs/pairs-noise-$a/judge/*.jsonl results/runs/pairs-h6-$a/judge/*.jsonl \
      results/runs/pairs-edits-$a/judge/*.jsonl results/runs/pairs-state-$a-*/judge/*.jsonl \
      > verdicts-$a.jsonl
  uv run hjr pairs-summary --items items-$a.jsonl --verdicts verdicts-$a.jsonl --tolerance 0.1 \
      > results/runs/pairs/summary-$a.md
done
```
