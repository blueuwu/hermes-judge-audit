# Larkspur shop: incident workspace

Larkspur is a mid-sized web shop. A customer request enters through `edge` (two nodes) and
checkout calls three internal services in order:

    browser -> edge -> checkout -> inventory   (reserve stock)
                               -> payments    (authorize and capture the charge)
                                    -> payments-db (PostgreSQL, through a connection pool)
                                    -> ledger      (append-only money ledger)

- edge: TLS termination and routing. Access logs are sampled for background traffic but every
  `POST /api/checkout` is logged. A checkout that times out upstream returns 504; an upstream
  error returns 502.
- checkout: orchestrates an order. It gives payments 8 s per attempt. Since v33 it retries a
  timed-out payment once with a new charge id.
- payments: one charge id per attempt. A charge whose client has gone away may still complete.
  Every capture is posted to the ledger, normally with an idempotency key per order.
- ledger: one entry per money movement. Settlement batches close entries every 15 minutes.

All timestamps are UTC. The incident under review happened on 2026-09-14 between roughly
13:30 and 15:05.

Evidence is released into `evidence/` in stages; see your instructions.
