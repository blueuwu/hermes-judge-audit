# Working on this repository

Read this before changing anything. `README.md` describes the study and how to run it, and
`configs/prereg.md` holds the pre-registered rules. Where this file and the prereg disagree, the
prereg wins.

The study is finished and written up in `reports/report.md`. The one open step is a confirmatory
pairs run on held-out boundaries, which needs its own dated amendment before any of its calls
(prereg note of 2026-10-14, *Scope*). Its paid calls count toward the $20 stop; measured spend
is in `results/runs/phase2/spend.md`.

Regenerating tables needs no model calls: `uv run hjr phase2-summary` (and `--truth v1`) writes
`results/runs/phase2/`, and `results/runs/pairs/README.md` gives the `hjr pairs-summary` command.

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

- **Audit.** The human verifier audit was done blind, without the judge's verdict or the
  stratum. It is finished; don't edit its records in `data/audit/`.
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
- **Processes.** On a shared machine, stop only processes your own run started. The author may
  have interactive Codex sessions open, so never kill `codex` or `node` by name.

## Known behaviour of the `strong` judge (Codex CLI)

- Many `codex exec` attempts hang with no output; the cause is unknown. In Phase 2, 139/403
  (weak) and 120/390 (strong) attempts timed out in the `prod-plain:strong` cells, and 16/280
  and 15/285 in `repair-v1:strong:evidence`.
- `hjr/codex.py` handles this:
  - It times each call out after 300 s and retries, up to 6 attempts.
  - It kills the whole process tree.
  - It runs at most 12 calls at once, at 6 calls per minute.
- A call that fails every attempt leaves no verdict. Rerunning the same replay command fills it
  in. Every Phase 2 call eventually succeeded.
