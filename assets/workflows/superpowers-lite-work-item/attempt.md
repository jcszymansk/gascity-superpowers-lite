Do the task card. Run:

    gc superpowers-lite attempt-start

It resets the worktree, then prints the card, the files you may change and,
after a rejected attempt, why it was rejected. The card is your whole task:
follow its Steps and Checklist, change only its files, and work only in the
printed worktree. Run every `done_when` command until all pass.

Finish with exactly one of these, then exit:

    gc superpowers-lite attempt-finish --summary "<what you changed and why>"
    gc superpowers-lite attempt-finish --blocked "<what stops you>"

Do not commit, push, or touch beads; attempt-finish commits for you.
