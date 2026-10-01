# ledger/entries.log format

One line per ledger event, UTC.

- `type=CAPTURE`: money taken from the customer for `order`, via payments `charge`.
- `type=REFUND`: money returned (negative amount), usually issued by support.
- `settlement`: a batch close; not a money movement.
- `idem`: the idempotency key payments sent with the entry. With `idempotency_mode=enforce`
  the ledger rejects a second capture for the same order key; with `log_only` it accepts it
  and only logs a warning on its side (not in this export). `none` means no key was sent.
- `src`: the payments pod (or support tool) that posted the entry.
