# Runbook: payments service

## Production configuration rules

These are checked in review; a deploy that violates one needs a written exception.

1. `db.pool.max_size` must be at least 40 in production. At peak, checkout produces about 25
   concurrent charges and each holds a connection for the whole authorize + capture.
2. `db.pool.acquire_timeout_ms` must not exceed `http.timeout_ms` + 2000.
3. `ledger.idempotency_mode` must be `enforce` in production. `log_only` records a duplicate
   key and accepts the entry anyway; it exists for ledger replays in staging.
4. `processor.retry.max_attempts` must be at most 3.
5. `logging.level` may be `debug` for at most 24 hours and needs no exception.

## Symptoms

- Charge latency p99 above 5 s with flat processor latency usually means pool waits. Check
  `pool.csv` (one row per minute: connections in use, pool size, waiters, worst wait).
- `status=abandoned reason=pool_wait_exceeded` means the charge never reached the processor.
- `client=gone` on a capture means checkout had already given up on that attempt.

## Rollback

Roll back with the deploy tool (`deployctl rollback payments --to <version>`). A rolling
rollback replaces one pod at a time; the pool size applies per pod as it restarts.
