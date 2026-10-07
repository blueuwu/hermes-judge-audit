# repair-v1 design iteration 3

Written and committed before any iteration 3 call. This is the last iteration Amendment 3 allows.
The families are the fixed item sets in `results/repair/families.json`, unchanged from
iteration 2. Errors are false-DONE where truth is not done or blocked, and false-CONTINUE where
truth is done.

## Changes from iteration 2

One change, to Step 2 of the system prompt (`hjr/repair.py`). Edit 1 stays exactly as it was in
iteration 2, although it was inert, so that only one variable changes. Edit 2 is replaced by a
more concrete version:

- Iteration 2: "Anything a requirement itself tells the agent to keep is not evidence of an unmet
  requirement."
- Iteration 3: "If the goal says to keep an old name in certain places, finding that old name in
  grep/search output is not evidence of an unmet requirement by itself. Check the location of
  the match against the goal: return CONTINUE on that basis only if the match is in a location
  the goal says must change."

The operational test is the location of the grep or search hit, not the presence of the old
name. The edit names no task, file or requirement from the design set.

## Prediction

The baseline is iteration 2. Each row gives a point estimate, with the range in parentheses.

| Family | Items | Iteration 2 | Iteration 3 expected | Why |
|---|---|---|---|---|
| FD-visible | 7 | 5 | 5 (4–6) | |
| FD-invisible | 17 | 17 | 17 (17) | |
| FD-blocked | 12 | 0 | 0 (0) | |
| FD-pilot-A1 | 4 | 3 | 3 (3–4) | |
| FD-pilot-TRUNC | 16 | 6 | 6 (5–7) | |
| FC-trace | 3 | 2 | 1 (0–2) | The new rule directly targets the old name in grep output. |
| FC-tail | 2 | 1 | 1 (1–2) | |
| FC-misread | 3 | 2 | 2 (2–3) | |
| FC-verification | 2 | 2 | 2 (1–2) | |
| Exposure: c2-01 done | 49 | 7 | 4 (3–5) | The iteration 2 regression came from grep hits on the kept old name, which the new rule addresses. |
| Exposure: c2-05 done | 59 | 1 | 1 (1–2) | |
| Other natural done | 115 | 3 | 3 (3–4) | |

| Aggregate | Iteration 2 | Iteration 3 expected |
|---|---|---|
| Natural false-DONE | 22/36 | 22/36 (21–23) |
| Natural false-CONTINUE | 11/223 | 8/223 (7–11), the sum of the three exposure rows |
| Pilot false-DONE | 9/32 | 9/16 (9–10) |
| Pilot false-CONTINUE | 2/16 | 2/16 (2–3) |

Results outside their predicted range are marked in the comparison after the run.

### Notes on the prediction

These notes were added under the prediction as given; they do not change its numbers.

- The pilot false-DONE row reads 9/16 as given. The pilot has 32 not-done items, so the
  denominator the results use is 32; the predicted count, 9 (9–10), is what is compared.
- A mechanistic reason to expect less movement on c2-01 than predicted. In the iteration 2
  regressions the old name was found in `docs/API.md` (`XpRfNT7`, `K2idkVg`, `tG5HgyL`, and
  FC-trace's `DjX2aYU`) and in the tests (`rmpzyYX`). The goal names both the docs and the tests
  as places that must change, and names only the deprecated alias's module as a place to keep the
  old name. Under the new location test, a hit in `docs/API.md` or the tests is in "a location the
  goal says must change", so the rule licenses CONTINUE there rather than withholding it. Only
  hits in the alias's own module are cleared. If that holds, Exposure: c2-01 done stays near 7
  (above the predicted range) and FC-trace near 2.

## Analysis notes

These are analysis notes only. They did not change the prompt.

- FD-invisible remains 17/17 because of a limit of the judge's view. The failing placement in
  `docs/API.md` never reaches the judge, so no prompt can catch it. It is recorded as a known
  blind spot, not a prompt failure.
- FD-visible did not move under a targeted edit in iteration 2. It is treated as a likely model
  limit on reading the `sha256sum -c` listing as the manifest's order, and is not pursued further.
- Per-family changes of one item are within noise at these sample sizes. Only the Exposure: c2-01
  done shift from 4 to 7 is treated as a real effect for repair-design purposes.

## Selection

After the run, the selection rule of Amendment 3 is applied as written across iterations 1, 2
and 3. There is no iteration 4.
