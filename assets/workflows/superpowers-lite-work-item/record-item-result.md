Record the item result and commit it.

Update the per-item summary with the changed files, every test command and its
result, and any remaining risk. If the item could not be completed, record the
blocker, make no commit, and close this step with `gc.outcome=fail`.

Otherwise commit the change in the item worktree (`work_dir` on the source
anchor) as one focused commit, or a few if the change has clearly separate
parts, in the repository's commit style. End each commit message with one
trailer block: `Bead: <source-anchor-id>` and any other trailers
(`Co-Authored-By:`) on consecutive lines with no blank line between them, since
git reads only the last paragraph as trailers. Commit only source, tests and
documentation that belong to the change: never the item summary, review
reports, logs or any other workflow artifact. Leave the worktree clean.

Do not invoke provider-native subagents or upstream plugin runtime commands.
