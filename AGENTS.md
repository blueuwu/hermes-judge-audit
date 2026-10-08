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
| Phase 2 replay, 6 cells × 3 samples | **done**, 1,584 + 1,620 parsed | `results/runs/phase2-{weak,strong}/` |
| Strong-judge sanity (paid API) | **done**, 60 + 60 parsed | `results/runs/phase2-sanity-{weak,strong}/` |
| Human verifier audit | **not started** | `hjr audit`, prereg "Human audit" |
| Phase 2 analysis tables | **not started** | `hjr phase2-summary` |
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
   commit the dated tolerance note to the prereg before any perturbation call.
4. **Write-up.** Update the README status line and add results.

## Setting up a fresh checkout

```bash
git clone --recurse-submodules https://github.com/blueuwu/hermes-judge-audit.git
cd hermes-judge-audit
uv sync
uv run pytest          # no network, keys, Docker or jobs/ needed
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
  - `hjr replay` on a finished run judges nothing, but it rewrites that run's `manifest.json`
    with the current commit and config hash.
  - If that happens, restore the file: `git checkout -- results/runs/<run>/manifest.json`.
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
