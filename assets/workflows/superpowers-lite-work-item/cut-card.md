Turn the work bead into task cards. Run:

    gc superpowers-lite cut-card-start

It prints the work bead, the worktree, where to write the cards, the card
template and an example card. Read the code the bead concerns in the worktree;
change nothing there. Work only from the bead and the worktree as it is at
HEAD: do not open other worktrees, other items' artifacts or cards, other
branches, or history beyond HEAD. An earlier card or a solution elsewhere is
not your input, and the printed example is the only card you need.

Size a card by the design it must settle, not by time or file count. A card
fits when it can settle every decision its change needs, so the executor only
implements: one coherent change and its tests, typically half a day of work
for a competent developer once the design is settled. A rename can touch
hundreds of files and stay one card. When the bead needs more than one card
can settle, cut it into several, numbered in the order they must be done. Each
card builds on the committed work of the cards before it, must pass its own
`done_when` on its own, and says in Out of scope what later cards will do.

Write one card per file, `1.md`, `2.md` and so on, in the printed directory:

- `kind`: `bugfix` when the card fixes wrong behaviour, `tdd-feature` when it
  adds new behaviour.
- `files`: every file the change may create or touch, tests included. Use a
  pattern (`*` within a directory, `**` across directories, as in
  `app/src/**/*Screen.kt`) for files you cannot name in advance or a change
  that sweeps many files. Files an attempt changes outside the list go to the
  reviewer.
- `done_when`: shell commands, run from the worktree root, that pass only when
  the card's work is done. When the bead lists its own done-when commands, the
  last card uses exactly those. Otherwise use as few as prove it, usually one
  run of the project's build tool that builds, lints and runs the full test
  suite (which includes the new tests). Every command starts a fresh process,
  so a separate run per test class repeats the whole build. A recursive grep
  needs `-I` (or `--include=` globs): repositories keep prebuilt binaries that
  still hold the strings a "these are gone" check looks for, and a card that
  greps them is refused.
- `## Interfaces`: signatures and types only, no bodies.
- `## Context`: quote the code the change depends on, exactly, with paths and
  line ranges, so the executor need not search. Quote what exists at HEAD,
  never what this or an earlier card will add.
- `## Steps`: what to change and why, and each test by name with the behaviour
  it pins down. Settle the decisions a junior developer would otherwise have to
  ask about, but write no code: the executor writes the tests and the
  implementation, and the check refuses a card that holds them.
- No `## Checklist` section; it is pasted for you.

Then run:

    gc superpowers-lite cut-card-finish

If it lists problems, fix the cards and run it again. If the bead cannot be
done at all as written (it is unclear, contradicts the code, or needs a
decision only a human can make), run instead:

    gc superpowers-lite cut-card-finish --blocked "<why>"

Size is a reason to block only when the bead needs more than ten cards;
otherwise split it.

Exit once either command reports the step closed.
