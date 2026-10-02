# Service config schema

Every file `configs/<service>.json` is one JSON object with exactly these keys (plus
`routes` for the gateway):

| Key | Rule | How to fix a violation |
|---|---|---|
| `name` | equals the file name without `.json` | set it to the file name |
| `owner` | the service's team address from `docs/OWNERS.md` | copy it from `docs/OWNERS.md` |
| `env` | `prod` or `staging` | (no automatic fix) |
| `port` | integer, equal to the service's entry in `docs/PORTS.md` | use the registry value |
| `replicas` | integer, at least 2 in `prod`, at least 1 in `staging` | raise it to the minimum |
| `timeout_ms` | integer from 100 to 30000 | convert strings to integers; a legacy `timeout_s` key becomes `timeout_ms` (seconds × 1000) |
| `log_level` | `debug`, `info`, `warn` or `error` | map the aliases `warning` → `warn` and `err` → `error` |

Gateway `routes`: each `{"path", "service", "port"}` must name an existing service, and
`port` must equal that service's registry port.

Values that do not violate a rule must not be changed.
