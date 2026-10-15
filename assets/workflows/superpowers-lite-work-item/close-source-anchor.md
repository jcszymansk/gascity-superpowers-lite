Close the work bead once its change has landed.

Resolve the source anchor as the worktree step did. Verify that it has
`lite.landed_commit` and `target`, that `refs/heads/<target>` in
`$GC_RIG_ROOT` contains the landed commit
(`git -C "$GC_RIG_ROOT" merge-base --is-ancestor <landed> refs/heads/<target>`),
and that the item summary at `gc.implementation.summary_path` on the item root
exists. If any check fails, leave the source anchor open and close this step
with `gc.outcome=fail` and the reason.

On success, close only the source anchor with `gc.outcome=pass` and a reason
naming the landed commit and the target branch. Read it back and verify it is
closed before closing this step. If `gc bd close` refuses because of an open
dependency, leave the anchor open, close this step with `gc.outcome=fail`, and
name the blocking bead in the reason; never force past it. Do not close the
drain-unit convoy, the parent convoy or any workflow root.

Do not invoke provider-native subagents or upstream plugin runtime commands.
