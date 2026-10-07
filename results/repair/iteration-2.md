# repair-v1 design iteration 2

Written and committed before any iteration 2 call. The families are fixed item sets defined in
`results/repair/families.json`. Errors are false-DONE where truth is not done or blocked, and
false-CONTINUE where truth is done.

## Changes from iteration 1

Two bullets are added to Step 2 of the system prompt (`hjr/repair.py`). Nothing else changes.
1. "Tool output shows the state as it is, not as the goal requires. When the goal constrains a
   property the output displays (order, format, placement, count), check that property directly
   instead of inferring it from the command succeeding."
2. "Anything a requirement itself tells the agent to keep is not evidence of an unmet
   requirement." The proposed example ("such as a deprecated alias") was dropped. It names a
   c2-01 requirement, and Amendment 3 bars that.

## Iteration 1's 10 natural false-CONTINUEs, by family

Each one was classified from the boundary's evidence view and the judge's three reasons.

| Family | Items | Boundaries | What the judge did |
|---|---|---|---|
| FC-trace | 3 | c2-01 `J5GieWj`, `tvmyuTo`, `DjX2aYU` | A grep shows the old name still in the docs, where the goal says to keep it; the judge read it as a use left un-updated. |
| FC-tail | 2 | c2-01 `4WSsu9A`, c2-05 `sgbgDfG` | The evidence keeps only the last 300 characters of a file read or `cat`. The judge took the cut start (a changelog section, the first manifest lines) as missing. |
| FC-misread | 3 | c2-05 `ExReb6p`, c3-06 `9KvAcQc`, c6-03 `nvnAHSw` | A superseded error inside a chained command (`… \|\| …`, then OK), an all-kinds row count beside the correct filtered one, and a contradiction inferred from a write warning with the final file shown correct. |
| FC-verification | 2 | c4-02 `BkkQkhA`, `MQjyF5w` | The response reports running an optional format check; the check is not among the last 3 tool calls, and the judge required it. |

Iteration 1's two pilot false-CONTINUEs form FC-pilot: a terse "fixed" claim with no tool output
(`a8-fixed`), and a long done report whose middle the view hides (`trunc-auth-migration-none`).

## Prediction

Iteration 1 errors are given, then the expected iteration 2 errors with a range.

| Family | Items | Iteration 1 | Iteration 2 expected | Why |
|---|---|---|---|---|
| FD-visible | 7 | 5 | 3 (2–5) | Edit 1's target. In 4 of the 5 misses a `sha256sum -c` listing shows the manifest out of filename order; the judge still has to see that this listing reflects the file's order. Low confidence. |
| FD-invisible | 17 | 17 | 17 (16–17) | The failing placement is not in the view. Edit 2 can only push toward DONE. |
| FD-blocked | 12 | 0 | 0 (0–1) | Untouched. |
| FD-pilot-A1 | 4 | 4 | 4 | No tool output to check. |
| FD-pilot-TRUNC | 16 | 6 | 6 (5–7) | No tool output; the hidden middle is a view limit. |
| FD-pilot-other | 12 | 0 | 0 (0–1) | Untouched. |
| FC-trace | 3 | 3 | 0 (0–1) | Edit 2's target. |
| FC-tail | 2 | 2 | 2 (2) | Edit 1 asks for direct checks, which favours reading a cut tail as the whole. Could not improve and may spread. |
| FC-misread | 3 | 3 | 3 (2–3) | Not addressed. |
| FC-verification | 2 | 2 | 2 (1–2) | Not addressed. |
| FC-pilot | 2 | 2 | 2 (1–2) | Not addressed. |
| Exposure: c2-01 done | 49 | 4 | 1 (1–3) | FC-trace fixed; the FC-tail item remains. |
| Exposure: c2-05 done | 59 | 2 | 3 (2–6) | Main risk of edit 1: more displayed listings checked directly, including cut ones. |
| Other natural done | 115 | 4 | 4 (3–6) | Not addressed; edit 1 may add a few. |

| Aggregate | Iteration 1 | Iteration 2 expected |
|---|---|---|
| Natural false-DONE | 22/36 | 20 (19–22) |
| Natural false-CONTINUE | 10/223 (4.5%) | 8 (6–12) |
| Pilot false-DONE | 10/32 | 10 (9–11) |
| Pilot false-CONTINUE | 2/16 | 2 (1–2) |

Natural false-CONTINUE above 11/223 breaks the 5% bound, which would make iteration 2
ineligible under the selection rule. The likeliest cause would be edit 1 on c2-05 done
boundaries.
