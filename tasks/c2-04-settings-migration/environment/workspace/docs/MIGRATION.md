# Settings schema v2

v2 settings live in `config/settings.json`, generated from the v1 `config/settings.ini`.

1. Each INI section becomes a top-level object with the same name, holding that section's
   keys, except as below.
2. `timeout` (seconds) is renamed `timeout_ms` and becomes an integer number of
   milliseconds.
3. `yes`/`no` become `true`/`false`. Integer values become JSON numbers. Every other value
   stays a string.
4. Keys removed in v2 are dropped: `server.legacy_mode`, `cache.legacy_keys`.
5. The top-level object has `"schema_version": 2`.
