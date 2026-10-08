# Controlled pairs: design draft (not adopted)

Written 2026-10-05 alongside the pairs code. Nothing here is part of the pre-registration until the
owner adopts it in a dated prereg note. The clarifications at the end are proposals only.

No judge calls or replay execution against real snapshots have been performed. No tolerance
is chosen here. The coordinator should resolve the statistical clarifications below before
perturbation calls and incorporate any accepted text into the preregistration.

## Inputs and use

`hjr pairs-build --boundaries <dev-only.jsonl> --cell prod-plain:flash:head4k
--out <pairs.jsonl>` emits noise-floor null/repeat items and H6 null/pre/post items. Each item
specifies three samples, an embedded BoundaryRecord, its cell, deterministic edit metadata,
the complete prompt hash and a complete head4k prompt hash. The timestamp comes from the
base boundary, so repeated prompts include identical time text. The loader checks split
before validating any trajectory and refuses a mixed dev/held-out file in full. An authorized
data custodian must supply dev-only input; the builder does not silently filter held-out data.

`--edits <edits.jsonl>` accepts ResponseEdit records: boundary_id, family, response and
rationale. H7 uses the original claim-free account plus the fixed CLAIM constant, requires
not_done truth and claim_free_base=true. Paraphrase/tone require meaning_preserving=true.
These attestations record review; code cannot establish semantic equivalence. Hedging and
error edits are also supported and recorded, but no confirmatory test is invented for them.
All response edits preserve every non-response field except the constructed boundary id.

Noise-floor records are inputs only. Future callers must run these first and wait for the
coordinator's dated tolerance note before any perturbation call. Building inputs does not
authorize or schedule calls.

For state inputs, `--kind state --snapshots <mapping.json> --executor module:factory` takes
an explicit mapping from dev boundary ids to extracted workspace directories. The adapter
implements ReplayExecutor.replay(workspace, events) and grade(task, workspace). There is no
default executor and no Docker invocation in the builder. The adapter must run commands in
order inside an isolated, network-disabled sandbox with the task's original image/runtime,
working directory, environment and tool semantics, capture ToolEvents using the harness's
exit/output-tail conventions, and grade with the frozen primary verifier. The builder copies
the supplied workspace independently, invokes only frozen, non-retired req mutants, verifies
exactly one true-to-false requirement change both before and after replay, and verifies the
null grade against the boundary. Replay that repairs the mutation or changes the null state
does not provide the intended contrast and is excluded.

Actual snapshot artifacts originate at `/logs/artifacts/boundaries/bNN.tgz`
(`hjr/harness/agent.py`) and are saved by Harbor in the trial's agent artifacts. The
trial's `agent/turns.jsonl` TurnRecord.snapshot identifies the archive; BoundaryRecord drops
that field during ingest. The corresponding grades are in `verifier/boundaries.json`.
Commands, tool names, exit codes and output tails are already in
BoundaryRecord.recent_tool_events. No jobs or private paths were opened for this work.

`hjr pairs-summary --items <pairs.jsonl> --verdicts <JudgeVerdict.jsonl>
--tolerance <recorded tolerance>` consumes stored verdicts only. Sample ids are 0, 1, 2;
incomplete items are listed and excluded. Agent models, input runs and phases get separate
tables; different serving arm/sub-arm identities within a cell are refused. E1 needs the
same base's complete null/repeat observations. Bootstrap streams derive from
`configs/seeds.toml` as `<global>:bootstrap:pairs:<comparison>` with 2,000 task resamples.
No new configuration file or tolerance default is needed. Repair inputs fail through the
existing judge code until repair-v1 is implemented; the builder does not invent that prompt.

## Proposed prereg clarification (not yet adopted)

The prereg says the pairs family is "Holm-corrected within itself", but H6 specifies only
"the paired per-item difference ... with a task-clustered bootstrap 95% CI" and E1 only a
CI equivalence rule. Proposed wording: Holm correction applies to the exact McNemar p-values
for H7, H8 in each evidence cell and the paired repair sensitivity comparisons. H6 keeps its
specified CI-above-zero rule and E1 keeps its specified whole-CI-within-tolerance rule;
neither receives an invented p-value. All these tests remain separate from H1-H5.

The prereg says "Sensitivity is computed over evidence-visible pairs only" without defining
its numerator. Proposed wording: sensitivity is the proportion of mutated arms judged not
DONE among replayable, evidence-visible pairs. Repair sensitivity is compared to
prod-plain:flash:evidence on their shared pairs, using exact McNemar on mutated-arm not-DONE
decisions and a task-clustered paired-difference interval. Null-arm decisions remain part of
each cell's main H8 DONE-rate contrast. The 80% bar is descriptive.

The prereg says "reproduce the recorded outputs". Frozen ToolEvents contain exit codes and
output tails, rather than complete raw stdout/stderr. Proposed wording: null replay must
reproduce each of the last three stored ToolEvents exactly (tool, command, exit and out_tail).
Visibility is equality of the actual evidence-cell prompts, after the real evidence rule,
so differences discarded by evidence truncation are invisible and excluded from sensitivity.

Existing Phase 2 tests that opened frozen trajectories were replaced with synthetic
truncation and stratified-sampling fixtures to keep the required full test run blind.
