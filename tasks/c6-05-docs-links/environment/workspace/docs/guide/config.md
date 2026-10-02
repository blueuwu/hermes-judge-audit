# Configuration

Install first ([installation](../setup/install.md)). Every setting can also come from the
environment ([variables](../reference/env.md)).

## TLS & certificates (v2)

Certificates are read from `~/.acme/certs`. Log TLS errors at debug level, see
[Logging](#logging).

## Logging

`log_level` is one of debug, info, warn, error. Variables override it, see
[environment variables](#env-vars).

## Environment variables

`ACME_LOG_LEVEL`, `ACME_PROXY`.
