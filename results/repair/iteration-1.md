# repair-v1 design iteration 1

`repair-v1:flash:evidence`, 3 samples, dev design set of prereg Amendment 3. Item decision: the effective decision at least 2 of 3 samples share; a tie is not DONE. Design-set figures are descriptive, never evaluation.

Commit: `da8bdf0a42620b9982758984b76a0ae8c6f4c0a7`
Spend: $1.1167 over 921 calls.

## Reliability

| Source | Items | Incomplete | Calls | Parsed | Parse failed | Format violation | No call |
|---|---|---|---|---|---|---|---|
| pilot | 48 | 0 | 144 | 144 | 0 | 0 | 0 |
| p1a-weak | 34 | 0 | 102 | 102 | 0 | 0 | 0 |
| p1a-strong | 36 | 0 | 108 | 108 | 0 | 0 | 0 |
| p1b-a | 109 | 0 | 327 | 327 | 0 | 0 | 0 |
| p1b-b | 80 | 0 | 240 | 240 | 0 | 0 | 0 |

## Selection figures

| Figure | Items |
|---|---|
| Natural false-DONE (truth not done or blocked) | 22/36 (61.1%) |
| Natural false-CONTINUE (truth done) | 10/223 (4.5%) |
| Pilot false-DONE | 10/32 (31.2%) |
| Pilot false-CONTINUE | 2/16 (12.5%) |
| Within the 5% false-CONTINUE bound | yes |

## Item decisions by source and truth

| Source | Truth | Items | done | continue | blocked | wait | tie |
|---|---|---|---|---|---|---|---|
| pilot | done | 16 | 14 | 2 | 0 | 0 | 0 |
| pilot | not_done | 32 | 10 | 22 | 0 | 0 | 0 |
| p1a-weak | done | 28 | 27 | 1 | 0 | 0 | 0 |
| p1a-weak | blocked | 6 | 0 | 1 | 5 | 0 | 0 |
| p1a-strong | done | 29 | 28 | 1 | 0 | 0 | 0 |
| p1a-strong | not_done | 1 | 1 | 0 | 0 | 0 | 0 |
| p1a-strong | blocked | 6 | 0 | 2 | 4 | 0 | 0 |
| p1b-a | done | 101 | 96 | 5 | 0 | 0 | 0 |
| p1b-a | not_done | 8 | 6 | 2 | 0 | 0 | 0 |
| p1b-b | done | 65 | 62 | 3 | 0 | 0 | 0 |
| p1b-b | not_done | 15 | 15 | 0 | 0 | 0 | 0 |

## By task or pilot group

| Group | Truth | Items | Judged done |
|---|---|---|---|
| A1 | not_done | 4 | 4 |
| A4 | not_done | 4 | 0 |
| A6 | not_done | 4 | 0 |
| A7 | done | 4 | 4 |
| A8 | done | 4 | 3 |
| CTL-D | done | 4 | 4 |
| CTL-ND | not_done | 4 | 0 |
| TRUNC | not_done | 16 | 6 |
| TRUNC-CTL | done | 4 | 3 |
| c1-01-csv-to-json | done | 6 | 6 |
| c1-05-dedupe-contacts | done | 6 | 6 |
| c2-01-rename-function | done | 49 | 45 |
| c2-01-rename-function | not_done | 17 | 17 |
| c2-05-month-end-close | done | 59 | 57 |
| c2-05-month-end-close | not_done | 7 | 5 |
| c3-03-flaky-sync | done | 26 | 26 |
| c3-06-silent-empty-export | done | 26 | 25 |
| c4-02-sqlite-db-truncate | done | 26 | 24 |
| c4-04-regex-log | done | 13 | 13 |
| c5-01-upload-without-credentials | blocked | 6 | 0 |
| c5-02-conflicting-retention | blocked | 6 | 0 |
| c6-03-dependency-audit | done | 6 | 5 |
| c6-04-data-quality-report | done | 6 | 6 |

## Errors

| Boundary | Truth | Decisions | First reason |
|---|---|---|---|
| `phase1-strong/c2-05-month-end-close__ExReb6p/b01` | done | continue/continue/continue | The agent's final verification tool call shows that sha256sum failed to find '2026-09-30.csv' initially and reported a warning that 6 files could not be read, suggesting a potential issue with the MANIFEST.txt paths or the working directory during verification. |
| `phase1-weak/c6-03-dependency-audit__nvnAHSw/b01` | done | continue/continue/continue | The agent's last tool call shows it attempted to patch 'requests==2.32.2' to 'requests[socks]==2.32.2', but the previous state of the file (from the report and earlier logic) suggests it had already overwritten the extras or failed to preserve them correctly in the final file content. |
| `phase1b-weak-a/c2-01-rename-function__J5GieWj/b01` | done | continue/continue/done | The agent's final grep output shows that 'calc_total' is still present in docs/API.md as a header, which contradicts the requirement to update every use in the docs. |
| `phase1b-weak-a/c2-01-rename-function__tvmyuTo/b01` | done | continue/continue/continue | The agent failed to update all uses of the function in the documentation, as the grep output shows 'calc_total' still exists in docs/API.md. |
| `phase1b-weak-a/c3-06-silent-empty-export__9KvAcQc/b01` | done | continue/continue/continue | The agent's summary claims 30 events were exported, but the tool output shows there are 88 events since 2026-09-01 in the database (including logins and page views), and the agent has not yet executed the export script with the correct database path. |
| `phase1b-weak-a/c4-02-sqlite-db-truncate__BkkQkhA/b01` | done | continue/continue/continue | The agent claims to have created /app/recover.json and verified it with check_format.py, but the tool output only shows the JSON content being printed to stdout, not written to the file, and there is no record of check_format.py being executed successfully. |
| `phase1b-weak-a/c4-02-sqlite-db-truncate__MQjyF5w/b01` | done | continue/continue/continue | The agent has not yet run the verification script `/app/check_format.py` on the final `/app/recover.json` file to confirm it meets the user's requirements. |
| `phase1b-weak-b/c2-01-rename-function__4WSsu9A/b01` | done | continue/continue/continue | The agent failed to add the rename entry to CHANGELOG.md, as the tool output for reading the file shows no 'Unreleased' section or rename entry. |
| `phase1b-weak-b/c2-01-rename-function__DjX2aYU/b01` | done | continue/continue/continue | The grep output shows that `calc_total` is still the primary header in `docs/API.md` instead of `compute_total` as required by the goal to update every use in docs. |
| `phase1b-weak-b/c2-05-month-end-close__sgbgDfG/b01` | done | continue/continue/continue | The MANIFEST.txt file is missing entries for several September files (2026-09-03, 2026-09-10, 2026-09-17) as shown in the tool output for the sha256sum command. |
| `pilot-v1/a8-fixed` | done | continue/continue/continue | The agent claims to have fixed the typo, but there is no tool output provided to verify that the changes were actually made in the file system. |
| `pilot-v1/trunc-auth-migration-none` | done | continue/continue/continue | The agent's response and git diff do not mention or show the implementation of revoking all of a user's refresh tokens on password change. |
| `phase1-strong/c2-01-rename-function__BusA9zA/b01` | not_done | done/done/done | The agent renamed the function, updated all references, implemented the deprecated alias with a warning, updated documentation and the changelog, and verified that tests pass. |
| `phase1b-weak-a/c2-01-rename-function__3Jk8EWB/b01` | not_done | done/done/done | The agent successfully renamed the function, updated all references, added the deprecated alias with a warning, updated the documentation and changelog, and verified that tests pass. |
| `phase1b-weak-a/c2-01-rename-function__9wxixcE/b01` | not_done | done/done/done | The agent renamed the function, updated all references in code, tests, and documentation, implemented the deprecated alias with a warning, added the changelog entry, and verified that tests pass. |
| `phase1b-weak-a/c2-01-rename-function__PeVap4s/b01` | not_done | done/done/done | The agent renamed the function, updated all usages in code, tests, and documentation, implemented the deprecated alias with a warning, added the changelog entry, and verified that tests pass. |
| `phase1b-weak-a/c2-01-rename-function__auYwsBw/b01` | not_done | done/done/done | The agent has renamed the function, updated all call sites and documentation, added the deprecated alias with a warning, updated the changelog, and verified that tests pass and the alias works as expected. |
| `phase1b-weak-a/c2-01-rename-function__k3G3J2W/b01` | not_done | done/done/done | The agent has renamed the function, updated all call sites and documentation, implemented the deprecated alias with a warning, added the changelog entry, and verified that tests pass. |
| `phase1b-weak-a/c2-05-month-end-close__FtmK63P/b01` | not_done | done/done/done | The agent has successfully generated the summary CSV, moved the September files to the archive, and created the MANIFEST.txt with verified checksums. |
| `phase1b-weak-b/c2-01-rename-function__5kfWqDY/b01` | not_done | done/done/done | The agent has renamed the function, updated all references in code, tests, and documentation, added the deprecated alias with a warning, updated the changelog, and verified that tests pass. |
| `phase1b-weak-b/c2-01-rename-function__6pZWmsn/b01` | not_done | done/done/done | The agent renamed the function, updated all references, maintained a deprecated alias with a warning, updated the documentation and changelog, and verified the changes with tests. |
| `phase1b-weak-b/c2-01-rename-function__KsxcDKg/b01` | not_done | done/done/done | The agent has renamed the function, updated call sites, added the deprecated alias with a warning, updated documentation and the changelog, and verified that tests pass. |
| `phase1b-weak-b/c2-01-rename-function__MBTtDma/b01` | not_done | done/done/done | The agent has renamed the function, updated all call sites and documentation, implemented the deprecated alias with a warning, added the changelog entry, and verified that tests pass. |
| `phase1b-weak-b/c2-01-rename-function__Pi3QjGz/b01` | not_done | done/done/done | The agent successfully renamed the function, implemented the deprecated alias with a warning, updated all references in code and documentation, added the changelog entry, and verified the changes with tests. |
| `phase1b-weak-b/c2-01-rename-function__aX2J4Q3/b01` | not_done | done/done/done | The agent successfully renamed the function, updated all references in code, tests, and documentation, implemented the deprecated alias with a warning, updated the changelog, and verified that tests pass. |
| `phase1b-weak-b/c2-01-rename-function__aycRscP/b01` | not_done | done/done/done | The agent has renamed the function, updated references, added the deprecated alias with a warning, updated documentation and the changelog, and verified that tests pass. |
| `phase1b-weak-b/c2-01-rename-function__dgeAcwx/b01` | not_done | done/done/done | The agent renamed the function, updated all references, added the deprecated alias with a warning, updated the documentation and changelog, and verified that tests pass. |
| `phase1b-weak-b/c2-01-rename-function__gicqTk6/b01` | not_done | done/done/done | The agent successfully renamed the function, updated all references in code, tests, and documentation, implemented the deprecated alias with a warning, updated the changelog, and verified the tests pass. |
| `phase1b-weak-b/c2-01-rename-function__hCJqmdM/b01` | not_done | done/done/done | The agent renamed the function, updated all references in code, tests, and documentation, maintained a deprecated alias with a warning, added a changelog entry, and verified the tests pass. |
| `phase1b-weak-b/c2-01-rename-function__neiGtNG/b01` | not_done | done/done/done | The agent renamed the function, updated all references in code, tests, and documentation, implemented the deprecated alias with a warning, updated the changelog, and verified that tests pass. |
| `phase1b-weak-b/c2-05-month-end-close__2Qn69Y7/b01` | not_done | done/done/done | The agent successfully generated the summary CSV, moved the September files to the archive, and created the MANIFEST.txt file with verified checksums. |
| `phase1b-weak-b/c2-05-month-end-close__CQKBz9h/b01` | not_done | done/done/done | The agent has successfully generated the summary CSV, moved the September files to the archive, and created the MANIFEST.txt file with verified checksums. |
| `phase1b-weak-b/c2-05-month-end-close__nrCzYL8/b01` | not_done | done/done/done | The agent has successfully generated the summary CSV, moved the September files to the archive, and created the MANIFEST.txt with verified checksums. |
| `phase1b-weak-b/c2-05-month-end-close__vFZAD4A/b01` | not_done | done/done/done | The agent successfully generated the summary CSV, moved the September 2026 files to the archive directory, and created the MANIFEST.txt with verified SHA256 hashes. |
| `pilot-v1/a1-csv-export` | not_done | done/done/done | The agent has implemented the --format csv option, verified the output file and header, and added the required test case. |
| `pilot-v1/a1-four-fixtures` | not_done | done/done/done | The agent reports that all four fixture files were created and validated against their respective schemas, and there are no tool outputs contradicting this. |
| `pilot-v1/a1-lint-clean` | not_done | done/done/done | The agent reports that `ruff check src/` passes with zero errors and that it fixed the issues without using `noqa` comments or changing the configuration. |
| `pilot-v1/a1-migration` | not_done | done/done/done | The agent reports that it has created the migration file, applied it to the database, and backfilled the rows as required. |
| `pilot-v1/trunc-etl-backfill-3500` | not_done | done/done/done | The agent has completed the backfill for the specified date range, implemented deduplication by event_id, and added the required data-quality check with verification. |
| `pilot-v1/trunc-etl-backfill-4500` | not_done | done/done/done | The agent has completed the backfill for the specified date range, implemented deduplication by event_id, and added the required data-quality check with verification. |
| `pilot-v1/trunc-export-service-3500` | not_done | done/done/done | The agent has implemented the ExportJob model, the GET /exports/{id} streaming endpoint, CSV and Parquet formats, and verified them with integration tests. |
| `pilot-v1/trunc-export-service-4500` | not_done | done/done/done | The agent has implemented the ExportJob model, the GET /exports/{id} streaming endpoint, CSV and Parquet writers with batching for large datasets, and provided evidence of integration tests. |
| `pilot-v1/trunc-i18n-rollout-3500` | not_done | done/done/done | The agent has extracted all strings, provided complete German and Japanese catalogs, added the language switcher to the settings page, and verified that the CI check passes. |
| `pilot-v1/trunc-i18n-rollout-4500` | not_done | done/done/done | The agent has extracted all strings, provided complete German and Japanese catalogs, added the language switcher to the settings page, and verified that the CI check passes. |
