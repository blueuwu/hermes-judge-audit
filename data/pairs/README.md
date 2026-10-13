# Controlled pairs: dev inputs (draft, for owner review)

- `dev-boundaries.jsonl`: the 70 `split == "dev"` lines of `data/frozen/phase1-weak.jsonl` (34)
  and `data/frozen/phase1-strong.jsonl` (36), byte-identical and in file order. `hjr pairs-build`
  reads truth for them from `data/truth/` (primary truth).
- `response-edits.draft.jsonl`: 96 `ResponseEdit` records on 24 bases, one per (task, agent arm),
  drawn with `random.Random("20261001:pairs-edits").choice` over each group's sorted boundary ids.
  Each base has one edit per family:
  - `hedging`: two completion or verification statements softened to uncertain language, as
    exact substitutions on the original. Nothing else changes.
  - `error`: one sentence inserted after the first line, naming a command that exited with an
    error, with no statement of whether it was resolved. Nothing else changes.
  - `paraphrase`: every sentence reworded in the same order and register.
  - `tone`: the same content in a terse, casual register.
  - `paraphrase` and `tone` keep every number, path, identifier, command and code block verbatim.
- `h7`: none drafted. Under primary truth, Phase 1a dev has one `not_done` boundary, and its
  account already makes a confident completion claim, so no base is claim-free.
- `claim_free_base` and `meaning_preserving` are false in every record. They are set only by the
  owner's review, and `pairs-build` refuses `paraphrase` and `tone` edits until they are set.
- No judge call has been made on any of these inputs.

## Inputs for `prod-plain:flash:head4k`, per agent arm

- `dev-weak.jsonl` (34) and `dev-strong.jsonl` (36): the same dev lines as `dev-boundaries.jsonl`,
  split by arm so that each arm is built, run and summarised on its own.
- `response-weak.jsonl` (170 items) and `response-strong.jsonl` (180): `hjr pairs-build --cell
  prod-plain:flash:head4k` on each, without `--edits`. Each base gets the noise-floor `null` and
  `repeat` items and the H6 `null`, `pre` and `post` items. The `.excluded.json` files are empty.
  The builder is deterministic, so a rebuild with the reviewed edits reproduces these items.
- Noise floor judged on 2026-10-13 with `hjr pairs-run --family noise` (runs `pairs-noise-weak`
  and `pairs-noise-strong`). No H6 or edit item has been judged.
