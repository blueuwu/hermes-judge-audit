# Stage 3 brief: Payments and its database pool

Released files: `payments/charges.log`, `payments/pool.csv`

Test the hypothesis that payments, not checkout, is the bottleneck. `charges.log` is an excerpt: only charges that were slow (over 5 s), retried or not captured. You need your stage 2 findings for the last question.

Record your answers in `/app/report/incident.json` under `"stage_3"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
| `pool_max_size_during_incident` | integer | Pool `max_size` while checkout was failing. |
| `saturated_from` | HH:MM | First minute in `pool.csv` where `in_use` equals `max_size`. |
| `saturated_until` | HH:MM | Last such minute. |
| `saturated_minutes` | integer | Number of rows where `in_use` equals `max_size`. |
| `peak_waiters` | integer | Highest `waiters`. |
| `peak_wait_ms` | integer | Highest `max_wait_ms`. |
| `late_captures` | list of strings | Charge ids captured after checkout had given up on them. |
| `first_timeout_minutes_after_saturation` | integer | Whole minutes (rounded down) from the start of `saturated_from` to the first checkout `PAYMENT_UPSTREAM_TIMEOUT`. |
