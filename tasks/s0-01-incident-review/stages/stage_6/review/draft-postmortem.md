# DRAFT postmortem: checkout outage 2026-09-14

Author: j.alvarez (checkout team). Status: draft, not reviewed.

## Summary

Between 14:07 and about 14:55 UTC, checkout failed for a large share of
customers. Payments latency rose sharply after a routine deploy and checkout requests timed
out. The service recovered after payments was rolled back.

## Claims to verify before review

- **C1.** The first checkout 504 reached a customer at 14:07:51.
- **C2.** Inventory errors caused most of the failed checkouts in the edge log; payments
  timeouts were a secondary effect.
- **C3.** 4 orders were charged twice.
- **C4.** The payments connection pool was saturated for more than 45 minutes.
- **C5.** D-2291 was approved under change ticket CHG-5521.
- **C6.** No checkout 504 occurred after the rollback (D-2297) completed.
- **C7.** Orders whose checkout failed were never charged, so no refunds are needed for them.

## Proposed actions (not part of this review)

1. Alert on pool waiters, not only on latency.
2. Make checkout reuse the charge id when it retries.
3. Block deploys that violate the runbook configuration rules.

## Timeline (incomplete)

- 13:41 D-2291 starts rolling out.
- 14:07 first customer-facing errors.
- 14:09 first page (edge).
- 14:47 rollback starts.
