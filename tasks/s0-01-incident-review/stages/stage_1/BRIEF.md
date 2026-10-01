# Stage 1 brief: Edge view and paging

Released files: `edge/access.log`, `pager.md`

Start with the customer-facing symptoms.

Record your answers in `/app/report/incident.json` under `"stage_1"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
| `count_by_status` | object | Every HTTP status in the edge access log mapped to its line count (keys are the status codes as strings). |
| `checkout_5xx_by_status` | object | Counts of 5xx responses on `POST /api/checkout`, keyed by status code. |
| `first_checkout_504` | HH:MM:SS | Timestamp of the first 504 on `POST /api/checkout`. |
| `last_checkout_504` | HH:MM:SS | Timestamp of the last 504 on `POST /api/checkout`. |
| `first_page_acked_by` | string | Who acknowledged the first high-severity page of the incident. |
| `payments_page_escalated_to` | string | Who the payments page escalated to. |
