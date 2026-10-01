# Stage 4 brief: Money movement

Released files: `ledger/FORMAT.md`, `ledger/entries.log`

Find out who was charged what. You need stages 1 to 3 to tell failed orders from successful ones.

Record your answers in `/app/report/incident.json` under `"stage_4"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
| `orders_charged_twice` | list of strings | Order ids with more than one `CAPTURE` entry. |
| `overcharge_total` | number | Total amount captured beyond one capture per order, for those orders (2 decimals). |
| `failed_orders_charged` | list of strings | Order ids whose checkout failed (504) but which have a `CAPTURE`. |
| `first_capture_without_idempotency_key` | HH:MM:SS | Timestamp of the first `CAPTURE` with `idem=none`. |
| `last_capture_without_idempotency_key` | HH:MM:SS | Timestamp of the last one. |
