# Stage 6 brief: Review and final report

Released files: `review/draft-postmortem.md`

Check a colleague's draft against everything you have found, re-reading earlier evidence where needed, then finalize. Besides `stage_6`, this stage fills the top-level `final` object (keys in the second table below).

Record your answers in `/app/report/incident.json` under `"stage_6"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
| `claims` | object | For each claim id `C1`..`C7` in the draft: `true` if the evidence supports it as written, else `false`. |

## `final` (top-level key)

| Key | Type | Question |
|---|---|---|
| `root_cause_service` | string | Service whose change caused the incident. |
| `trigger_deploy` | string | Deploy id. |
| `root_cause_settings` | list of strings | Dotted keys of the settings that caused the customer impact. |
| `checkout_504s` | integer | Checkout 504s in the edge log. |
| `orders_charged_twice` | integer | Number of orders charged twice. |
| `failed_orders_charged` | integer | Number of failed orders that were charged. |
| `customer_impact_window` | list of 2 strings | First and last checkout 504, `HH:MM:SS`. |
