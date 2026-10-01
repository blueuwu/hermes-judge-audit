# Pager export, 2026-09-14 (UTC)

| Page | Opened | Alert | Severity | Routed to | Acknowledged | Resolved |
|---|---|---|---|---|---|---|
| PAGE-309 | 12:51:40 | inventory: reservation expiry job lagging > 10 min | low | inventory on-call (a.mensah) | 12:55:02 by a.mensah | 13:20:11 |
| PAGE-311 | 14:09:12 | edge: checkout 5xx ratio > 2% (5 min) | high | edge on-call (m.okafor) | 14:12:40 by m.okafor | 14:58:30 |
| PAGE-312 | 14:15:03 | payments: charge latency p99 > 5 s (5 min) | high | payments on-call primary (t.brandt) | not acknowledged | 14:57:44 |
| PAGE-312 | 14:30:03 | (escalation after 15 min without ack) | high | payments on-call secondary (r.lindqvist) | 14:31:10 by r.lindqvist | 14:57:44 |
| PAGE-313 | 14:22:40 | inventory: reserve error rate > 1% (5 min) | low | inventory on-call (a.mensah) | auto-resolved | 14:24:40 |
| PAGE-314 | 14:36:15 | edge: checkout 5xx ratio > 5% (5 min) | high | edge on-call (m.okafor) | 14:36:52 by m.okafor | 14:58:30 |

## Responder chat excerpts

- 14:13:05 m.okafor: edge looks healthy itself, the 5xx are all on POST /api/checkout. Pulling
  the access log. Not paging checkout yet.
- 14:24:51 m.okafor: inventory page auto-resolved, probably unrelated, saw one 502 earlier too.
- 14:33:20 m.okafor: raising the edge alert threshold to 5% for now so the pager stops flapping
  while we look (D-2295). This does not change traffic.
- 14:31:40 r.lindqvist: picking up payments. Charge latency is through the roof, looking at the
  pool metrics.
- 14:46:02 r.lindqvist: going to roll payments back to v40, details in the deploy log.
- 14:58:30 m.okafor: checkout ratio back under 1% for five minutes. Resolving edge pages.
