# Controlled pairs: dev inputs (draft, for owner review)

- `dev-boundaries.jsonl`: the 70 `split == "dev"` lines of `data/frozen/phase1-weak.jsonl` (34)
  and `data/frozen/phase1-strong.jsonl` (36), byte-identical and in file order. `hjr pairs-build`
  reads truth for them from `data/truth/` (primary truth).
- `response-edits.draft.jsonl`: 96 `ResponseEdit` records on 24 bases, one per (task, agent arm),
  drawn with `random.Random("20261001:pairs-edits").choice` over each group's sorted boundary ids.
  Each base has one edit per family:
  - `hedging`: the completion and verification statements, and in some responses a few nearby
    statements such as a diagnosis or a refusal, softened to uncertain language (two to about
    eight per response), as exact substitutions on the original. Nothing else changes.
  - `error`: one sentence inserted as its own paragraph after the first line, naming a command
    that exited with an error, with no statement of whether it was resolved. Nothing else
    changes.
  - `paraphrase`: every sentence reworded in the same order and register.
  - `tone`: the same content in a terse, casual register.
  - `paraphrase` and `tone` keep every number, path, identifier, command and code block verbatim.
- `h7`: none drafted. Under primary truth, Phase 1a dev has one `not_done` boundary, and its
  account already makes a confident completion claim, so no base is claim-free.
- Owner review (2026-10-14): `meaning_preserving` is true on all 48 `paraphrase` and `tone`
  records, after four fixes: two `tone` openers that weakened or dropped the completion claim,
  one `paraphrase` that turned "warns" into "raises", and the `error` sentence, moved to its own
  paragraph (on weak `c5-02` it also names a different error, since the original account already
  reports the one drafted). `claim_free_base` stays false: there is no `h7` record.
- No judge call has been made on any of these inputs.

## Inputs for `prod-plain:flash:head4k`, per agent arm

- `dev-weak.jsonl` (34) and `dev-strong.jsonl` (36): the same dev lines as `dev-boundaries.jsonl`,
  split by arm so that each arm is built, run and summarised on its own.
- `response-edits-weak.jsonl` and `response-edits-strong.jsonl`: the reviewed edits split by arm,
  48 each, byte-identical lines; their union is `response-edits.draft.jsonl` (checked by a test).
- `response-weak.jsonl` (218 items) and `response-strong.jsonl` (228): `hjr pairs-build --cell
  prod-plain:flash:head4k --edits response-edits-<arm>.jsonl` on each. Each base gets the
  noise-floor `null` and `repeat` items and the H6 `null`, `pre` and `post` items. Each edit base
  also gets one `edit` item per family, compared with its noise-floor `null`. The `.excluded.json`
  files are empty.
- Rebuilt 2026-10-14. The 170 weak and 180 strong items of the first build, on which the noise
  floor was judged, are reproduced byte-for-byte. sha256:
  - `response-weak.jsonl` `76e8a4d46fd1e3365e666b55427683a2bb70f99881a242bc9d89483a9a58659c`
  - `response-strong.jsonl` `0f5e7eb698078a6fad09fd19dbb7b4454a2b0f91b7810357e4f503c1a8922d73`
  - `response-edits-weak.jsonl` `b121460f391cd85363b26ab0b90156ccdb4047d4c467e0d85c8774ddd24eb7e1`
  - `response-edits-strong.jsonl` `61e5c731dc863f147cea7e75eafe3b1479f14769bcbad330ead9a30144cc954c`
- Noise floor judged on 2026-10-13 with `hjr pairs-run --family noise` (runs `pairs-noise-weak`
  and `pairs-noise-strong`). No H6 or edit item has been judged.

## State pairs (H8), evidence-view cells, per agent arm

Built on 2026-10-14 with `hjr pairs-state` (adapter `hjr/state_replay.py`) for the cells
`prod-plain:flash:evidence`, `repair-v1:flash:evidence` and `repair-v1:strong:evidence`. No judge
call has been made on them.

- Each dev boundary's Phase 1 snapshot (`jobs/`, not committed) is copied twice. Every frozen,
  non-retired requirement mutant of its task is applied to one copy, and both copies replay the
  boundary's last three recorded calls through Hermes's own tools at `ffc74885`, offline, in the
  task's image. Grades come from the frozen verifier.
- Every snapshot graded back to its recorded primary truth, so no pair was lost to the grading
  path.
- The replay rule is that of the prereg note of 2026-10-14: each replayed ToolEvent (tool,
  command, exit, output tail) equals the record, with the `execute_code` timing fields
  `duration_seconds` and `execution_count` masked. The same mask applies to the visibility
  check. Under exact equality, the first build gave weak 10 pairs (4 evidence-visible) and
  strong 4 (1); the masked rule keeps all of them and adds 5 weak and 4 strong.

| | weak | strong |
|---|---:|---:|
| Pairs built | 15 | 8 |
| of which evidence-visible | 7 | 2 |
| Excluded: null replay differs from the record | 41 | 64 |
| Excluded: mutant does not flip exactly its requirement | 40 | 46 |
| Excluded: replay changes the requirement contrast | 52 | 33 |
| Excluded: mutant does not apply to this snapshot | 9 | 15 |
| Excluded: target requirement not satisfied in the base | 3 | 2 |

Files: `state-{weak,strong}.jsonl` (items), `.excluded.json` (one row per boundary and mutant),
`.log` (the build log).

Replay fidelity, measured on an unmutated copy of all 70 dev boundaries (210 calls):
- Exact: `terminal` 67/95, `read_file` 37/38, `execute_code` 17/43, `write_file` 15/15,
  `clarify` 6/6, `patch` 0/10, `search_files` 0/2, `tool_search` 0/1.
- 16 `execute_code` calls differ only in the timing fields `duration_seconds` and
  `execution_count`. Masking those fields, as the replay rule now does, makes 12 more
  boundaries fully replayable (35 instead of 23 of 70).
- Most other differences are not adapter faults. The snapshot is taken after the last three calls
  ran, so a replay meets the state those calls left behind. A patch applies again, a test that
  failed before the fix now passes, a file the agent moved is gone.
- Two calls depend on session context the replay lacks, and the adapter supplies it. `clarify`
  gets the headless answer `hermes chat -Q` gives. An overwriting `write_file` is preceded by an
  unrecorded `read_file` of the same path, standing in for the session's earlier read, so that
  the read-before-write guard does not refuse it.
