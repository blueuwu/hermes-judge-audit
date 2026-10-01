# Stage 2 brief: Checkout service

Released files: `checkout/app.log`, `escalations.md`

Explain the edge 5xx from checkout's side, and answer the escalations.

Record your answers in `/app/report/incident.json` under `"stage_2"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
| `checkout_errors_by_code` | object | Count of checkout `ERROR` lines per `code`. |
| `dominant_failing_upstream` | string | The upstream service behind most failed checkouts. |
| `orders_succeeded_after_retry` | integer | Orders whose payment timed out on attempt 1 but succeeded on attempt 2. |
| `escalations` | object | For each ticket id: `failed:payments`, `failed:inventory`, `succeeded_after_retry` or `succeeded`, from what checkout actually did with that order (match the order id). |
