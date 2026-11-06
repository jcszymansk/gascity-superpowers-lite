Turn the work bead into one task card. Run:

    gc superpowers-lite cut-card-start

It prints the work bead, the worktree, where to write the card and the card
template. Read the code the bead concerns in the worktree; change nothing
there. Then write the card to the printed path:

- `kind`: `bugfix` when the bead reports wrong behaviour, `tdd-feature` when it
  asks for new behaviour.
- `files`: every file the change may create or touch, tests included. The
  executor may change nothing else.
- `done_when`: shell commands, run from the worktree root, that pass only when
  the work is done: the new or changed test by name, then the project's build,
  lint and full test commands.
- `## Context`: paste the code the change depends on, with paths and line
  ranges, so the executor need not search.
- `## Steps`: concrete steps a junior developer could follow without asking.
- No `## Checklist` section; it is pasted for you.

Then run:

    gc superpowers-lite cut-card-finish

If it lists problems, fix the card and run it again. If the bead cannot be done
as one card (unclear, too large, needs a decision), run instead:

    gc superpowers-lite cut-card-finish --blocked "<why>"

Exit once either command reports the step closed.
