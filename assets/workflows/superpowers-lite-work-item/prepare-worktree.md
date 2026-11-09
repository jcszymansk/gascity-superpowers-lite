Create this item's worktree on its target branch. Run:

    gc superpowers-lite prepare-worktree

It resolves the work bead, fails the item when a bead it is blocked by has
not landed, bases the worktree on the target branch when it exists (else the
default branch), records `work_dir`, `target` and the base commit, and closes
this step. On any failure it closes the step as failed and
prints why. Either way, exit when it returns. Do not run git or bd yourself.
