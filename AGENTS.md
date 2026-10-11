# Working on this repository

Read this before changing anything. `README.md` describes the study and how to run it, and
`configs/prereg.md` holds the pre-registered rules. Where this file and the prereg disagree, the
prereg wins.

## Where the project stands (2026-10-08)

| Stage | State | Where |
|---|---|---|
| Pilot, soak gate, task suite, split | done | `results/runs/pilot-v1/`, `results/soak/`, `configs/split.toml` |
| Phase 1a trajectories (178 boundaries: weak 88, strong 90) | frozen | `data/frozen/phase1-{weak,strong}.jsonl` |
| Mutation suite and frozen primary verifier | done | prereg note of 2026-10-05, `results/mutants/` |
| Primary truth (regrade) | done | `data/truth/phase1-{weak,strong}.jsonl`, `results/regrade/` |
| Phase 1b (weak, enrichment) | done | `results/phase1b/` |
| repair-v1 design and freeze | done, tag `repair-freeze-v1` | `results/repair/`, prereg Amendment 3 |
| Phase 2 replay, 6 cells × 3 samples | **done**, 1,582 + 1,620 parsed (weak has 2 parse failures) | `results/runs/phase2-{weak,strong}/` |
| Strong-judge sanity (paid API) | **done**, 60 + 60 parsed | `results/runs/phase2-sanity-{weak,strong}/` |
| Human verifier audit | draw committed, audit **not started** | `hjr audit`, `data/audit/draw.json`, prereg "Human audit" |
| Phase 2 analysis tables | done | `results/runs/phase2/summary.md`, `summary-v1.md`, `spend.md` |
| Controlled counterfactual pairs (H6–H8, E1) | not started | `hjr pairs-build`, `hjr pairs-summary`, prereg "Controlled counterfactual pairs" |
| Write-up (README results, report) | not started | |

## Next steps, in order

1. **Human audit.** It must be done by the project owner, not an agent. Its records are the
   human labels. Two parts can't run in a cloud checkout:
   - `hjr audit run` reads the Harbor job directories under `jobs/`. Those are about 4 GB, stay
     on the owner's machine and are gitignored.
   - It opens files with `os.startfile`, which is Windows-only.

   An agent may prepare the draw if the owner asks. The draw needs only committed files:

   ```bash
   uv run hjr audit draw \
     --boundaries data/frozen/phase1-weak.jsonl --boundaries data/frozen/phase1-strong.jsonl \
     --verdicts results/runs/phase2-weak/judge/prod-plain__self-weak__head4k.jsonl \
     --verdicts results/runs/phase2-strong/judge/prod-plain__self-strong__head4k.jsonl \
     --primary-verifier 63ce540
   ```

   Check the flags against `hjr audit draw --help` and the prereg before running. The draw is
   seeded and logged once to `data/audit/draw.json`, so it can't be redrawn: commit it as is.
2. **Phase 2 analysis.** `uv run hjr phase2-summary` writes `results/runs/phase2/summary.md`,
   and `--truth v1` writes the sensitivity tables to `summary-v1.md`. Neither makes model calls.
   Audit findings never change the primary analysis. The prereg's *Truth* rules say how a
   verifier error found in the audit becomes a sensitivity rerun.
3. **Controlled pairs.** These run on dev boundaries only. Measure the noise floor first, then
   commit the dated tolerance note to the prereg before any perturbation call. The builder's
   inputs, and three proposed prereg clarifications the owner has not adopted, are in
   `docs/pairs-design-draft.md`.
4. **Write-up.** Update the README status line and add results.

## Setting up a fresh checkout

```bash
git clone --recurse-submodules https://github.com/blueuwu/hermes-judge-audit.git
cd hermes-judge-audit
uv sync --extra harness   # the tests import harbor
uv run pytest             # no network, keys, Docker or jobs/ needed
uv run ruff check . && uv run ruff format --check .
```

- Hermes is a git submodule pinned at `ffc74885` (`third_party/hermes-agent`). Never move it.
- Judge calls need `OPENROUTER_API_KEY` in `.env`; copy `.env.example`.
- The `strong` judge runs through the Codex CLI, pinned to 0.159.3 and logged in. It is
  configured as the `codex-cli` endpoint in `configs/judge_variants.toml`. A cloud sandbox
  usually has neither, so plan no `strong` calls there. Phase 2 needs none.
- `private/` (planning notes) and `jobs/` (raw Harbor runs) are not in the repository.
- Harbor and Docker steps (`harness/`, `tasks/`) are for generating trajectories. They are
  finished, and this project doesn't need them again.

## Rules

- **Audit blinding.** The owner audits the verifier blind: without the judge's verdict, and
  without the stratum, which encodes whether verifier and judge agree. Until the audit is done:
  - Never show the owner per-boundary judge verdicts, false-DONE lists, or which boundary
    falls in which stratum.
  - That covers PR descriptions, commit messages, comments and chat summaries.
  - Don't quote or summarise `data/audit/draw.json`, which lists every boundary's stratum.
  - The aggregate tables of `hjr phase2-summary` are fine.
- **Pre-registration.**
  - Don't edit existing text in `configs/prereg.md`.
  - A change of plan is a new dated amendment or note, committed before the work it governs.
  - Throttling and rate limits are not part of arm identity, so changing them needs no
    amendment.
- **Frozen inputs.** Don't modify these:
  - `data/frozen/`, `data/truth/` and `data/mutants/`.
  - `configs/phase2.toml` and the `[models]` entries in `configs/judge_variants.toml`.
  - Anything under `tasks/*/tests/`, the primary verifier.
  - The `repair-v1` prompt.
- **Finished runs.** Treat `results/runs/<run>/` of a finished run as read-only.
  - `hjr replay` on a finished run judges nothing and leaves its `manifest.json` untouched.
  - The manifest is rewritten only when the replay adds a record, so never rerun a finished run
    with new variants or samples.
- **Held-out data.**
  - Held-out boundaries are open, since `repair-freeze-v1` is an ancestor of HEAD.
  - Pairs and any repair design still use dev boundaries only.
- **Spend.**
  - Paid Phase 2 calls stop at $20 without a further amendment; `uv run hjr cost --run-id <run>`
    shows measured spend.
  - The OpenRouter workspace has its own credit cap.
  - A sudden run of 403 errors on every call usually means that cap was reached, not a code
    fault.
- **Arms are never pooled.** Report every number per agent arm (weak, strong). The analysis
  code refuses to mix arms or sub-arms.
- **Git.**
  - Commit messages are one line, saying what changed and the key number.
  - No co-author or tool-attribution trailers, and no generated-by lines in commits, PRs or
    files.
  - Keep history linear and don't force-push `main`.
  - Never commit `.env` or keys.
- **Processes.** On a shared machine, stop only processes your own run started. The owner may
  have interactive Codex sessions open, so never kill `codex` or `node` by name.

## Known behaviour of the `strong` judge (Codex CLI)

- About 10–30% of `codex exec` calls hang with no output. The cause is unknown.
- `hjr/codex.py` handles this:
  - It times each call out after 300 s and retries, up to 6 attempts.
  - It kills the whole process tree.
  - It runs at most 12 calls at once, at 6 calls per minute.
- A call that fails every attempt leaves no verdict. Rerunning the same replay command fills it
  in.
- In `phase2-strong`, 135 attempts timed out and every call eventually succeeded.

## Cloud work queue (owner away 2026-10-08 to 2026-10-11)

Each item is one session and one PR. Nothing here needs `jobs/`, the Codex CLI or an API key.
- Order: run W1 first, because W4 uses its tables. W2 and W3 can run at any time.
- Start every session's prompt with the preamble, then add the item's prompt.

**Preamble:**

> Read AGENTS.md first and follow its rules. Work on a new branch and open a PR. Never push to
> `main`, and never merge. Make no paid model calls and set no API key. Never edit existing
> prereg text or anything listed as frozen. The owner must stay blind for the human audit, so
> never put per-boundary judge verdicts, audit strata or the contents of `data/audit/draw.json`
> in a PR description, commit message, comment or summary. Before opening the PR, run
> `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`, and say in the PR
> what passed.

**W1: analysis tables, audit draw, spend note.** Branch `phase2-analysis`.

> Run `uv run hjr phase2-summary` and `uv run hjr phase2-summary --truth v1`, and commit
> `results/runs/phase2/`. Then run the audit draw exactly as in "Next steps" step 1. Check its
> flags against `hjr audit draw --help` first. Commit `data/audit/draw.json` without opening or
> quoting it. Then run `uv run hjr cost --run-id <run>` for phase2-weak, phase2-strong,
> phase2-sanity-weak and phase2-sanity-strong, and for the earlier runs that count toward the
> same cap (prereg Amendment 3): `probe-p2` and every `repair-i*` run (15). Write
> `results/runs/phase2/spend.md`: billed spend per run and in total, against the $20 stop on
> paid Phase 2 calls, with the Codex CLI calls listed as unbilled. In the PR, list anything in the tables that looks inconsistent with
> the prereg (missing cells, unexpected counts, refused pooling). Don't interpret the results.

**W2: code fixes.** Branch `fixes`.

> 1. `hjr replay` on a run where every item is already on disk still rewrites that run's
>    `manifest.json` with the current commit and config hash. Make it leave the manifest
>    untouched when nothing new was judged, and add a test.
> 2. Add `windows-latest` to the CI workflow as a matrix next to `ubuntu-latest`, keeping the
>    steps the same. If a test fails only on Windows, fix the cause, not the test.
> 3. Bring the README's Layout table up to date with the modules and result directories that
>    exist: `hjr/audit.py`, the pairs code, `hjr/regrade.py`, `results/repair/`,
>    `results/phase1b/` and so on.
>
> Keep the three as separate commits.

**W3: response-pair edits, for review.** Branch `pairs-response-draft`.

> Read the prereg sections "Controlled counterfactual pairs" and "Hypotheses on pairs",
> `docs/pairs-design-draft.md` and `hjr/pairs.py`. Use dev boundaries only.
> - Write a dev-only boundaries file by filtering both `data/frozen/phase1-*.jsonl` on
>   `split == "dev"`. `pairs-build` refuses a file that mixes dev and held-out boundaries.
> - Draft `ResponseEdit` records for the families `h7` (a confident completion claim, only on
>   not_done-truth boundaries with a claim-free account), `hedging`, `error`, `paraphrase` and
>   `tone`. The H6 caveat items, before and after the 4,000-character cut, are generated by the
>   builder itself, so don't draft them. Write the edits to
>   `data/pairs/response-edits.draft.jsonl`.
> - Leave `claim_free_base` and `meaning_preserving` false in the committed draft. Only the
>   owner's review may set them.
> - To check that the edits build, copy the draft to a temp directory outside the repo with
>   those flags set true. Run `hjr pairs-build --kind response --cell prod-plain:flash:head4k`
>   on the copy, with `--out` also in the temp directory. Commit neither file.
> - Make no judge calls.
> - In the PR, give per-family counts, the build's item and exclusion counts, and a few example
>   edits for review. Don't adopt the proposed clarifications in the draft.

**W4: write-up skeleton (after W1 is merged).** Branch `writeup-draft`.

> From `results/runs/phase2/summary.md` and the prereg, update the README status line. Draft a
> README "Phase 2 results" section in the style of "Pilot findings": short bullets, numbers
> per agent arm, and no pooling across arms. Keep it to aggregate rates and tests per
> hypothesis. Put placeholders, marked TODO, for the human audit, the pairs and anything that
> depends on them. If the owner pasted a report outline into this prompt, also draft
> `reports/report.md` from it with the same rules.

**Not for an unattended session:**
- The pairs noise-floor and perturbation calls: they are paid, and the tolerance is the owner's
  call.
- State pairs (H8): they need `jobs/`.
- The audit itself.
- Any `strong` judge call.
