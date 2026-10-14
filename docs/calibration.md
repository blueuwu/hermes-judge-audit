# Calibration scaffold

`uv run hjr calibrate --from-run phase2 --dry-run` plans new judge configurations
over stored endpoints. Dry run is the default. It reads local files, prints item
counts, calls as items times samples, and estimated USD for every variant. Prices
in `calibrate.toml` are explicitly stub prices per call, not provider quotes.
No client is constructed, no replay is invoked, and no files are written in dry run.
`--variants hermes-contract,hermes-subgoals` selects names; space separated names
also work.

An ordinary source run needs a manifest with hashed boundary inputs and stored
judge records. The command selects unique boundary IDs represented in those records,
not every boundary in the input file. The `phase2` directory contains summary tables,
so its configured alias selects `phase2-weak` and `phase2-strong`. Counts are printed
separately by source run and agent arm. Samples repeated under old judge cells do not
multiply the endpoint count. The original runs remain read-only.

`--live` uses the existing `replay()` engine with a calibration prompt builder.
It requires `--confirm-spend <usd>` and refuses when the estimate exceeds that cap.
It separately refuses when the exact billed Total row in
`results/runs/phase2/spend.md` plus the estimate exceeds the pre-registered $20 stop.
An absent or malformed spend total fails closed. The cap applies to the whole selected
batch. Stub estimates cannot enforce actual billing, especially with retries. Before
any future live use, replace stub prices with defensible estimates, update the spend
ledger, and commit any required dated preregistration amendment. This scaffold branch
exercises live dispatch only with replay and clients mocked. It makes no live calls.

Live preflight checks all task-specific prompt material before constructing clients.
Outputs go to new `calibrate-<batch>-<index>` directories per source arm and variant,
with the config snapshot, its hash, source run, estimate and cap recorded.
Credentials must already be supplied by the caller; calibration does not load `.env`.

All new model, endpoint, sampling, price and variant definitions live in
`configs/calibrate.toml`. Calibration never loads the frozen
`configs/judge_variants.toml`. Keeping them separate protects the identity of completed
evaluation cells. A test pins the frozen file's SHA256 with canonical LF line endings
so Windows checkout conventions do not change the hash.

Both included templates come directly from the pinned Hermes copy's
`hermes_cli/goals.py` at commit `ffc74885c5f6eb75f6c134fb4eef86d734066623`.
The completion-contract variant requires a per-task contract. Its contracts table is
empty with a TODO. Someone who has seen the verifier could leak truth into the judge
by writing contracts from those checks, so this scaffold supplies none and never
substitutes the boundary's existing contract. Live execution refuses missing contracts.
The subgoals variant likewise leaves its per-task criteria empty for later user input
and refuses live execution without them. Both variants are still priced in dry run.

To add a variant, add a uniquely named `[variants.<name>]` table with a template,
model key, supported view and positive sample count. Add its model and endpoint in the
same config and a stub USD per-call price under `stub_prices`. The supported templates
are the two named Hermes templates. A new template requires a reviewed extension to
the calibration template registry and prompt builder, with parity tests. Contracts
are keyed by task ID under the variant's `contracts` table, using Hermes contract
fields. Subgoals are lists of criteria keyed by task ID under `subgoals`.

`hjr.calibrate.compute_metrics(decisions, truth)` returns `NotImplemented`. Agent A's
table code will plug into that interface after merging. Calibration implements no metrics.
