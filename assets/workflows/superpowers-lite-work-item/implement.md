Inspect the work bead before changing anything.

This item has no build plan. The source anchor bead is the whole
specification: its title, description, design notes and acceptance criteria.
Resolve the source anchor the same way the worktree step did, read its
`work_dir`, and work only in that worktree, never in the launcher checkout.
Read context path `{{context_path}}` when it is set, and the repository's own
agent instructions (`AGENTS.md`, `CLAUDE.md`, `README.md`) for build and test
commands.

Use the installed `test-driven-development` and `systematic-debugging` skills.
For a bug, reproduce it first and find its cause; the fix goes at the cause,
not at the symptom. Confirm the bead is small enough to finish in this item.
If it is not, or its acceptance criteria are missing or contradict the code,
record that in the summary and fail this step instead of guessing.

Write the per-item summary (schema `gc.build.implementation-summary.v1`) under
the item's artifact directory, record its path as `gc.implementation.summary_path`
on the item root, and include a task context note for the following steps:
the acceptance criteria as you read them, the first behaviour to drive with a
failing test, and the focused and broader test commands. The later steps refer
to "the approved plan"; for this item that means this note and the bead.

Do not invoke provider-native subagents or upstream plugin runtime commands.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
