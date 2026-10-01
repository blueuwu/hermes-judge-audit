# Stage 5 brief: Change history and configuration

Released files: `config/payments-v40.yaml`, `config/payments-v41.yaml`, `deploys/history.json`, `runbooks/payments.md`

Find the change behind everything so far.

Record your answers in `/app/report/incident.json` under `"stage_5"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
| `trigger_deploy` | string | Deploy id that caused the incident. |
| `trigger_completed_at` | HH:MM:SS | When that deploy completed. |
| `changed_settings` | list of strings | Dotted keys (`db.pool.max_size` style) whose value differs between payments v40 and v41, excluding `service.version`. |
| `saturation_cause` | string | The dotted key that explains the pool saturation. |
| `duplicate_cause` | string | The dotted key that explains why the ledger accepted duplicate captures. |
| `minutes_deploy_to_first_checkout_504` | integer | Whole minutes (rounded down) from the trigger deploy completing to the first checkout 504. |
| `rollback_deploy` | string | Deploy id of the rollback. |
| `runbook_violations` | list of strings | Dotted keys whose v41 value breaks a runbook configuration rule. |
