# Changelog

## Unreleased

- Add `Client.drain()` to wait for in-flight jobs.
- Retry publishes on broker failover.
- Drop support for Python 3.10.

## 1.4.2 - 2026-08-01

- Fix a reconnect loop when the broker closes idle connections.

## 1.4.1 - 2026-07-15

- Pin retrylib to 1.4.2, which fixes jitter on Python 3.14.
