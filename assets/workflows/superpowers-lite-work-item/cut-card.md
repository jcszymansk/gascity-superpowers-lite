Turn the work bead into one task card. Run:

    gc superpowers-lite cut-card-start

It prints the work bead, the worktree, where to write the card, the card
template and an example card. Read the code the bead concerns in the worktree;
change nothing there. Work only from the bead and the worktree as it is at
HEAD: do not open other worktrees, other items' artifacts or cards, other
branches, or history beyond HEAD. An earlier card or a solution elsewhere is
not your input, and the printed example is the only card you need. Then write
the card to the printed path:

- `kind`: `bugfix` when the bead reports wrong behaviour, `tdd-feature` when it
  asks for new behaviour.
- `files`: every file the change may create or touch, tests included. Use a
  pattern (`*` within a directory, `**` across directories, as in
  `app/src/**/*Screen.kt`) for files you cannot name in advance or a change
  that sweeps many files. There is no limit on how many: a rename may touch
  hundreds of files and still be one easy card. Judge a card's size by effort
  and risk, about an hour for a junior developer, never by file count. Files
  an attempt changes outside the list go to the reviewer.
- `done_when`: shell commands, run from the worktree root, that pass only when
  the work is done. When the bead lists its own done-when commands, use exactly
  those. Otherwise use as few as prove it, usually one run of the project's
  build tool that builds, lints and runs the full test suite (which includes
  the new tests). Every command starts a fresh process, so a separate run per
  test class repeats the whole build; on a large project each costs minutes.
- `## Interfaces`: signatures and types only, no bodies.
- `## Context`: quote the code the change depends on, exactly, with paths and
  line ranges, so the executor need not search. Quote what exists, never what
  the change will add.
- `## Steps`: what to change and why, and each test by name with the behaviour
  it pins down. Settle the decisions a junior developer would otherwise have to
  ask about, but write no code: the executor writes the tests and the
  implementation, and the check refuses a card that holds them.
- No `## Checklist` section; it is pasted for you.

Then run:

    gc superpowers-lite cut-card-finish

If it lists problems, fix the card and run it again. If the bead cannot be done
as one card (unclear, too large, needs a decision), run instead:

    gc superpowers-lite cut-card-finish --blocked "<why>"

Exit once either command reports the step closed.
