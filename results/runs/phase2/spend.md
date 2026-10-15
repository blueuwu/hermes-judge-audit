# Phase 2 spend against the $20 stop

Measured with `uv run hjr cost --run-id <run>` on 2026-10-09; the controlled pairs runs were
added on 2026-10-14. Cost is what the provider billed,
summed over the stored call records of each run. The runs are the ones that count toward the $20
stop on paid Phase 2 calls: the Phase 2 replay and its strong-judge sanity check (Phase 2 design
amendment, 2026-10-02), `probe-p2`, the 15 `repair-i*` design runs (Amendment 3), and the controlled pairs runs (prereg note of
2026-10-14).

The `strong` cells run through the Codex CLI on my subscription. Those calls are not
billed per call: they are listed here with their counts and add nothing to the total.

| Run | Billed calls | Billed spend | Codex CLI calls (unbilled) |
|---|---|---|---|
| `phase2-weak` | 1,056 | $0.8770 | 528 |
| `phase2-strong` | 1,080 | $0.9058 | 540 |
| `phase2-sanity-weak` | 60 | $0.1004 | 0 |
| `phase2-sanity-strong` | 60 | $0.1217 | 0 |
| `probe-p2` | 60 | $0.0215 | 40 |
| `repair-i1-pilot` | 144 | $0.1477 | 0 |
| `repair-i1-p1a-weak` | 102 | $0.1264 | 0 |
| `repair-i1-p1a-strong` | 108 | $0.1416 | 0 |
| `repair-i1-p1b-a` | 327 | $0.3997 | 0 |
| `repair-i1-p1b-b` | 240 | $0.3013 | 0 |
| `repair-i2-pilot` | 144 | $0.1527 | 0 |
| `repair-i2-p1a-weak` | 102 | $0.1296 | 0 |
| `repair-i2-p1a-strong` | 108 | $0.1455 | 0 |
| `repair-i2-p1b-a` | 327 | $0.4112 | 0 |
| `repair-i2-p1b-b` | 240 | $0.3098 | 0 |
| `repair-i3-pilot` | 144 | $0.1560 | 0 |
| `repair-i3-p1a-weak` | 102 | $0.1320 | 0 |
| `repair-i3-p1a-strong` | 108 | $0.1478 | 0 |
| `repair-i3-p1b-a` | 327 | $0.4187 | 0 |
| `repair-i3-p1b-b` | 240 | $0.3150 | 0 |
| `pairs-noise-weak` | 204 | $0.1543 | 0 |
| `pairs-noise-strong` | 216 | $0.1767 | 0 |
| `pairs-h6-weak` | 306 | $0.3318 | 0 |
| `pairs-h6-strong` | 324 | $0.3590 | 0 |
| `pairs-edits-weak` | 144 | $0.1115 | 0 |
| `pairs-edits-strong` | 144 | $0.1178 | 0 |
| `pairs-state-weak-prod-plain-flash` | 135 | $0.1297 | 0 |
| `pairs-state-weak-repair-v1-flash` | 135 | $0.1650 | 0 |
| `pairs-state-weak-repair-v1-strong` | 0 | $0.0000 | 135 |
| `pairs-state-strong-prod-plain-flash` | 72 | $0.0767 | 0 |
| `pairs-state-strong-repair-v1-flash` | 72 | $0.0953 | 0 |
| `pairs-state-strong-repair-v1-strong` | 0 | $0.0000 | 72 |
| **Total** | **6,831** | **$7.1792** | **1,315** |

- Billed total: $7.18 of the $20 stop, leaving $12.82.
- By group: Phase 2 replay $1.78, sanity check $0.22, `probe-p2` $0.02, repair design $3.44
  (i1 $1.12, i2 $1.15, i3 $1.17), controlled pairs $1.72 (noise $0.33, H6 $0.69, edits $0.23,
  state $0.47).
- The Phase 2 design amendment estimated the billed calls at about $7.60, of which about $4.50
  was the API sanity check. Measured: $1.78 for the replay and $0.22 for the sanity check.
- Codex CLI calls: 1,068 in the Phase 2 replay (`prod-plain:strong:head4k` and
  `repair-v1:strong:evidence`, both arms), 40 in `probe-p2` and 207 in the pairs state cell
  `repair-v1:strong:evidence` (weak 135, strong 72).
- Only stored call records are counted. A transport-failed attempt leaves no record, so any
  provider charge for one is not in this table; the OpenRouter workspace's own usage page is the
  check on that.
