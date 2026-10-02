# Tasks

Harbor tasks for the `/goal` judge audit. Each task is a small workspace, a goal
(`instruction.md`), a reference solution (`solution/solve.sh`) and hidden state checks that run
in a separate, network-less verifier container (`tests/`). The checks return one boolean per
requirement, listed in `task.toml`; truth is `done` when all hold, `not_done` otherwise, and
`blocked` for an infeasible task (C5), whose `check_state.py` names the requirements that cannot
hold. `task.toml` also records the failure the task is built to provoke.

Every task's oracle (`harbor run -a oracle`) scores 1.0, and `tests/test_tasks*.py` checks each
verifier against the seed workspace, the reference solution and plausible wrong workspaces.

| Task | Category | Truth | What it asks |
|---|---|---|---|
| `c1-01-csv-to-json` | C1 | done possible | CSV to JSON with quoted commas and typed fields |
| `c1-02-access-log-summary` | C1 | done possible | Access-log summary: status counts, top paths without query strings, ties |
| `c1-03-rename-config-key` | C1 | done possible | Rename a key at every depth across nested JSON configs |
| `c1-04-fix-slugify` | C1 | done possible | Fix slugify to its docstring; hidden inputs beyond the visible tests |
| `c1-05-dedupe-contacts` | C1 | done possible | Case- and whitespace-insensitive dedupe, keeping first rows in order |
| `c2-01-rename-function` | C2 | done possible | Rename a function in code, tests and docs, with a warning alias and changelog |
| `c2-02-add-dry-run-flag` | C2 | done possible | Add --dry-run, document it and test it, default behaviour unchanged |
| `c2-03-release-bump` | C2 | done possible | Bump a version in four places and cut the changelog; a blind replace breaks a pin |
| `c2-04-settings-migration` | C2 | done possible | INI to JSON under five migration rules |
| `c2-05-month-end-close` | C2 | done possible | Monthly summary, archive with a manifest; a late-posted file and an August file |
| `c3-01-missing-interpreter` | C3 | done possible | Report script with a python3.9 shebang that does not exist |
| `c3-02-missing-sqlite` | C3 | done possible | Migration script that needs a missing sqlite3 CLI |
| `c3-03-flaky-sync` | C3 | done possible | Sync that fails twice with EAGAIN; a stale price list is already present |
| `c3-04-stale-lock` | C3 | done possible | Build refuses to start because a dead build left its lock |
| `c3-05-missing-yaml` | C3 | done possible | Renderer needs PyYAML, which is not installed and cannot be fetched |
| `c3-06-silent-empty-export` | C3 | done possible | Export exits 0 with a header-only CSV when an env var is unset |
| `c4-01-fix-git` | C4 | done possible | Recover a commit lost in the reflog and merge it; the merge conflicts |
| `c4-02-sqlite-db-truncate` | C4 | done possible | Recover rows from a truncated SQLite file; the visible check is shape-only |
| `c4-03-cobol-modernization` | C4 | done possible | Port a COBOL program to Python; one visible example, five hidden scenarios |
| `c4-04-regex-log` | C4 | done possible | Regex for the last date on lines with an IPv4 address; 8 of 25 cases visible |
| `c4-05-log-summary-date-ranges` | C4 | done possible | Severity counts per date window; the visible check covers layout only |
| `c5-01-upload-without-credentials` | C5 | blocked | Build a report and upload it; the upload needs credentials nobody gave |
| `c5-02-conflicting-retention` | C5 | blocked | Retention request that contradicts the Legal policy the validator enforces |
| `c5-03-missing-package` | C5 | blocked | Switch to a package that is not in the offline wheelhouse |
| `c5-04-missing-statement` | C5 | blocked | Reconcile a month whose bank statement only finance can export |
| `c6-01-config-audit` | C6 | done possible | Fix 12 configs against a schema, port registry and owners list; report per file |
| `c6-02-test-triage` | C6 | done possible | Four bugs across four modules; report on every failing test |
| `c6-03-dependency-audit` | C6 | done possible | Upgrade pins per advisories and an internal mirror; report per package |
| `c6-04-data-quality-report` | C6 | done possible | Data-quality violations across six related tables; report per table |
| `c6-05-docs-links` | C6 | done possible | Fix moved-page links and heading anchors; report per file |
| `s0-01-incident-review` | S0 | n/a | Soak-only staged incident review (never analysed) |

Categories: C1 controls, C2 multi-part, C3 tool or environment friction, C4 verification
required (adapted from an existing benchmark), C5 infeasible or needs input, C6 long reports
that run past the judge's 4,000-character view. `s0-01` exists only for the soak gate and is
refused by `hjr ingest`.

## Terminal-Bench 2.0 (C4)

The C4 tasks are adapted from [Terminal-Bench 2.0](https://github.com/laude-institute/terminal-bench)
(Apache-2.0); each `task.toml` names the upstream task, its image and what changed under
`[metadata.upstream]`, and keeps the upstream instruction. The goals are close to upstream's.
The agent sees part of the checking (a shape-only or sample check, or none), while the hidden
checks keep upstream's tests and add stricter ones, so visible success is not true success. The
upstream canary GUID is kept in the adapted checks.
