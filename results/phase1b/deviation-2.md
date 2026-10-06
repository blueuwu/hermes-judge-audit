# Phase 1b deviation 2: pre-analysis rule for reported pools

**2026-10-06. Addendum to the Phase 1b note, written after Stage A and before Stage B, and
before any Phase 1b metric is computed.** The note (`results/phase1b/note.md`, frozen at
`c0cd890`) is unchanged. This addendum sets how each reported pool is analyzed. The code for
task-macro rates, the task bootstrap and the per-pool rule is still the TODO in the note. It
will be committed and tested on synthetic data before it is run on any Phase 1b data.

*Rule.* The <5 distinct not-done task rule applies separately to every reported pool. The Stage
A uniform all-task pool may report pooled micro and task-macro rates with task bootstrap; its
bootstrap clusters are the tasks represented in that pool, and any CI limitations should reflect
the actual number of task clusters. Dev-only and held-out-only pools report per-task counts only
when they fail the <5 distinct not-done task rule. For the Stage A+B selected-task enrichment
pool, there are 5 task clusters, so task-bootstrap CIs are reported as coarse. Stage A alone is
reported as the uniform sample; Stage A+B on selected tasks is reported as enrichment yield, not
prevalence.

*Details.*
- Not-done rates:
  - Stage A is the uniform sample. Its pool has 16 task clusters, including tasks with zero
    not-done boundaries. It may report a pooled micro rate and a task-macro rate with task
    bootstrap.
  - Stage A+B on the 5 selected tasks is reported as enrichment yield, not prevalence.
  - Per-task not-done rates on the selected tasks are reported from Stage B only. Stage A counts
    on those tasks determined the selection.
- Judge metrics conditioned on primary truth pool Stage A and Stage B. They are reported as
  micro and task-macro, with a task bootstrap over the tasks that contribute boundaries to that
  metric.
- The <5 distinct not-done task rule applies separately to every reported pool. A pool that
  fails it reports per-task counts only. A pool that passes with few clusters reports its CIs as
  coarse and states the cluster count.
- Held-out-only metrics, and pooled metrics that include held-out boundaries, are sealed until
  `repair-freeze-v1`. Before that freeze, only dev-only results may be computed or viewed.
