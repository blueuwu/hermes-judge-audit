# Controlled pairs (constructed inputs only)

DONE requires 2 of 3 samples. Intervals bootstrap whole tasks (2,000 resamples).
H6 is pre-cut flip minus post-cut flip; H7/H8 are edited minus null DONE rates.
H6 is tested by an exact one-sided sign-flip test on per-task differences (alpha 0.05);
its bootstrap CI is descriptive. Each agent arm is a separate claim.
E1 is edit flip minus paired identical-input flip. Repair compares sensitivity
(mutated not DONE) on the same evidence-visible pairs.
H7's 30-point and H8's 80% reference bars are descriptive, not gates.
E1, H8 and the repair comparisons are descriptive (prereg note of 2026-10-14):
their p-values are shown but carry no verdict.

E1 reference tolerance: 0.1 (no family is called inert).

| Cell | Identical-input flips (Wilson) | Task CI |
|---|---|---|
| phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence | 0/15 | counts only |
| phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 0/34 (0.0%, 0.0–10.2) | [0.0000, 0.0000] |
| phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence | 0/15 | counts only |
| phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence | 0/15 | counts only |

| Evidence cell | Sensitivity (Wilson) | Task CI |
|---|---|---|
| phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence | 0/7 | counts only |
| phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence | 3/7 | counts only |
| phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence | 3/7 | counts only |

| Edit family | Cell | Edit flips vs null (exact 95% CI) | Paired identical-input flips |
|---|---|---|---|
| error | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 0/12 (0.0–26.5%) | 0/12 |
| hedging | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 0/12 (0.0–26.5%) | 0/12 |
| paraphrase | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 0/12 (0.0–26.5%) | 0/12 |
| tone | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 0/12 (0.0–26.5%) | 0/12 |

| Test | Cell | n | Difference [95% CI] | Exact p | Holm p | Reading |
|---|---|---|---|---|---|---|
| H8 | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence | 7 | +0.00 items [+0.00, +0.00] (difference × n) | 1.0 | 1.0 | descriptive: no confirmatory claim |
| E1/paraphrase | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 12 | +0.00 items [+0.00, +0.00] (difference × n) | n/a | None | descriptive: no inertness claim |
| E1/tone | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 12 | +0.00 items [+0.00, +0.00] (difference × n) | n/a | None | descriptive: no inertness claim |
| H6 | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:head4k | 34 | 0.0588 [0.0000, 0.1389] | 0.25 (sign-flip, 2/2 tasks positive) | None | H6 not established |
| H8 | phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence | 7 | -3.00 items [-6.30, +0.00] (difference × n) | 0.25 | 1.0 | descriptive: no confirmatory claim |
| H8 | phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence | 7 | -3.00 items [-6.30, +0.00] (difference × n) | 0.25 | 1.0 | descriptive: no confirmatory claim |
| H8/repair sensitivity | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence->repair-v1:flash:evidence | 7 | +3.00 items [+0.00, +6.30] (difference × n) | 0.25 | 1.0 | descriptive: no confirmatory claim |
| H8/repair sensitivity | phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence->repair-v1:strong:evidence | 7 | +3.00 items [+0.00, +6.30] (difference × n) | 0.25 | 1.0 | descriptive: no confirmatory claim |

Exclusions:

- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c1-01-csv-to-json__zdjLNpd/b01/pairs/state/req:input_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c1-01-csv-to-json__zdjLNpd/b01/pairs/state/req:input_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c1-01-csv-to-json__zdjLNpd/b01/pairs/state/req:input_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c3-03-flaky-sync__7JDLcQb/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c3-03-flaky-sync__7JDLcQb/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c3-03-flaky-sync__7JDLcQb/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c3-03-flaky-sync__Q94qMeL/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c3-03-flaky-sync__Q94qMeL/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c3-03-flaky-sync__Q94qMeL/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c3-03-flaky-sync__Q94qMeL/b01/pairs/state/req:apply_script_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c3-03-flaky-sync__Q94qMeL/b01/pairs/state/req:apply_script_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c3-03-flaky-sync__Q94qMeL/b01/pairs/state/req:apply_script_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c3-03-flaky-sync__sXxBAPY/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c3-03-flaky-sync__sXxBAPY/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c3-03-flaky-sync__sXxBAPY/b01/pairs/state/req:discontinued_kept: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c3-03-flaky-sync__sXxBAPY/b01/pairs/state/req:apply_script_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c3-03-flaky-sync__sXxBAPY/b01/pairs/state/req:apply_script_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c3-03-flaky-sync__sXxBAPY/b01/pairs/state/req:apply_script_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c6-04-data-quality-report__dEjnxmn/b01/pairs/state/req:data_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c6-04-data-quality-report__dEjnxmn/b01/pairs/state/req:data_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c6-04-data-quality-report__dEjnxmn/b01/pairs/state/req:data_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:prod-plain:flash:evidence phase1-weak/c6-04-data-quality-report__Ros9WXM/b01/pairs/state/req:data_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:flash:evidence phase1-weak/c6-04-data-quality-report__Ros9WXM/b01/pairs/state/req:data_unchanged: evidence_invisible
- phase1-weak:z-ai/glm-5.3-flash:1a:repair-v1:strong:evidence phase1-weak/c6-04-data-quality-report__Ros9WXM/b01/pairs/state/req:data_unchanged: evidence_invisible
