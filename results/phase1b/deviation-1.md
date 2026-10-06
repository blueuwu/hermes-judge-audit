# Phase 1b deviation 1: aborted Stage A run

**2026-10-06. Addendum to the Phase 1b note, written before Stage A is rerun.** The note
(`results/phase1b/note.md`, frozen at `c0cd890`) is unchanged. This addendum records a crashed
Stage A launch, its cause, the fix, and a rule for any later crash.

*What happened.* Stage A was launched as job `phase1b-weak-a` per the note at 09:07:52Z. Harbor
exited with code 1 at 09:09:46Z. Of 320 scheduled trials, 7 had started and none completed.
- `c2-02-add-dry-run-flag`, `c2-03-release-bump`, `c2-04-settings-migration`,
  `c2-05-month-end-close` and `c3-01-missing-interpreter`: `UnicodeDecodeError`.
- `c2-01-rename-function`: `CancelledError`, cancelled when the job went down.
- `c3-02-missing-sqlite`: no `result.json`.

The cause is in Harbor 0.23.0, not in the harness. `populate_context_post_run` in
`harbor/agents/installed/hermes.py` (line 349) reads the trial's `agent/hermes-session.jsonl`
with `Path.read_text()` and no encoding argument. Python on this machine defaults to cp1252. The
session file is UTF-8 and contains byte 0x81, which cp1252 cannot decode. The
`UnicodeDecodeError` propagated through Harbor's TaskGroup and ended the whole job instead of
failing one trial.

*Fix.* Stage A is launched with `PYTHONUTF8=1` set in the launch environment, which turns on
Python's UTF-8 mode so the same read decodes as UTF-8. It is not set in `.env`. This is not a
Harbor or harness code change: Harbor is unpatched, and `hjr/harness/` is still identical to
`73820f2`. The agent runs inside the task container, truth comes from the frozen primary
verifier, and the in-loop judge request is unchanged, so none of them depends on the host's
text encoding.

A new check, `uv run --no-sync hjr preflight`, fails unless `sys.flags.utf8_mode` is 1 and
`locale.getpreferredencoding()` names the UTF-8 codec. It compares codec names because Python
reports the encoding as `utf-8` in UTF-8 mode. It must pass before any Phase 1b launch.

Verification, on the five session files that raised the error, read with `Path.read_text()`
and no encoding as Harbor does. Only sizes and outcomes were printed.

| Trial | Bytes | With `PYTHONUTF8=1` | Without it |
|---|---|---|---|
| `c2-02-add-dry-run-flag__aiccnwd` | 40427 | ok, 40343 characters | `UnicodeDecodeError` |
| `c2-03-release-bump__e9YFpVr` | 46102 | ok, 45986 characters | `UnicodeDecodeError` |
| `c2-04-settings-migration__YBsKQqf` | 29708 | ok, 29590 characters | `UnicodeDecodeError` |
| `c2-05-month-end-close__FcBK79j` | 37498 | ok, 37400 characters | `UnicodeDecodeError` |
| `c3-01-missing-interpreter__TUmLoph` | 45458 | ok, 45350 characters | `UnicodeDecodeError` |

With the variable set, `sys.flags.utf8_mode` was 1 and the preferred encoding `utf-8`.
Without it, they were 0 and `cp1252`, and every read failed as in the aborted run.

*Phase 1a parity.* Phase 1a sessions contained non-ASCII bytes. All 88 `hermes-session.jsonl`
files in `jobs/phase1-weak` and all 90 in `jobs/phase1-strong` have a nonzero count of bytes
at or above 0x80, and every one of them contains bytes that cp1252 cannot decode. No Phase 1a
run record shows `PYTHONUTF8` or UTF-8 mode. That covers both job `config.json`, `job.log` and
`result.json` files, both console logs (`jobs/phase1-weak.log`, `jobs/phase1-strong.log`), the
repository and its history, the Git Bash and PowerShell histories, and the user and machine
environment. The Phase 1a job logs show Windows paths, and the installed Harbor 0.23.0 files
date from 2026-10-01, before Phase 1a ran on 2026-10-02.

*Disposition.*
- The aborted job is archived at `jobs/_aborted/phase1b-weak-a-attempt1/`. Its manifest,
  `jobs/_aborted/phase1b-weak-a-attempt1.sha256`, lists the sha256 of each of its 87 files and
  itself has sha256 `41eed499230b864df72515317d8faa828e2cabb20f3c687e7d8d5943769743bb`.
- All 7 trials are discarded. Nothing from the aborted job is ingested, regraded or analyzed.
  `hjr ingest` reads only the job directory it is given, so it never reads `jobs/_aborted/`.
- No container from the aborted job was left running.
- Stage A is rerun from scratch under the original job name, `phase1b-weak-a`, with the
  command in the note.

*Spend.* The aborted run spent $0.031939 on the dedicated Phase 1b key. It counts against the
$20 cap, leaving $19.968061.

*New rule, pre-committed for Stage A and Stage B.* Any harness-level crash aborts the entire
stage. The partial job is archived with a manifest. Nothing from it is ingested, and the job is
not resumed. The stage then reruns from scratch. A failed trial in a job that completes is not a
crash and is excluded as the note says.
