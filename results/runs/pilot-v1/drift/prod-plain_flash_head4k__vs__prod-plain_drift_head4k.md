# Drift: `prod-plain:flash:head4k` → `prod-plain:drift:head4k`

- Paired items: 48 (unpaired: {'baseline_only': 0, 'candidate_only': 0})
- Call-level disagreement: 23/240 (9.6%) (DONE→CONTINUE 15, CONTINUE→DONE 3)
- Item-level disagreement (majority decision): 5/48 (10.4%)

## Decision transitions (calls, baseline → candidate)

| Baseline \ Candidate | done | continue | blocked |
|---|---|---|---|
| done | 125 | 15 | 0 |
| continue | 3 | 92 | 0 |
| blocked | 0 | 5 | 0 |

## Disagreement by stratum

| Stratum | Calls changed | Items changed |
|---|---|---|
| category=A1 | 0/20 (0.0%) | 0/4 (0.0%) |
| category=A4 | 0/20 (0.0%) | 0/4 (0.0%) |
| category=A6 | 0/20 (0.0%) | 0/4 (0.0%) |
| category=A7 | 0/20 (0.0%) | 0/4 (0.0%) |
| category=A8 | 0/20 (0.0%) | 0/4 (0.0%) |
| category=CTL-D | 0/20 (0.0%) | 0/4 (0.0%) |
| category=CTL-ND | 0/20 (0.0%) | 0/4 (0.0%) |
| category=TRUNC | 18/80 (22.5%) | 4/16 (25.0%) |
| category=TRUNC-CTL | 5/20 (25.0%) | 1/4 (25.0%) |
| scenario=auth-migration | 15/25 (60.0%) | 3/5 (60.0%) |
| scenario=etl-backfill | 5/25 (20.0%) | 1/5 (20.0%) |
| scenario=export-service | 3/25 (12.0%) | 1/5 (20.0%) |
| scenario=i18n-rollout | 0/25 (0.0%) | 0/5 (0.0%) |

## Correctness against truth (item majority)

Both correct 33, baseline only 2, candidate only 3, neither 10. Exact McNemar p = 1.
NeMo Evaluator verdict: INCONCLUSIVE.

## Flipped items

| Boundary | Category | Truth | Baseline | Candidate |
|---|---|---|---|---|
| pilot-v1/trunc-auth-migration-4500 | TRUNC | not_done | done | continue |
| pilot-v1/trunc-auth-migration-8000 | TRUNC | not_done | done | continue |
| pilot-v1/trunc-auth-migration-none | TRUNC-CTL | done | done | continue |
| pilot-v1/trunc-etl-backfill-1000 | TRUNC | not_done | blocked | continue |
| pilot-v1/trunc-export-service-1000 | TRUNC | not_done | continue | done |
