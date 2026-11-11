Do the task card. Run:

    gc superpowers-lite attempt-start

It resets the worktree, then prints the card, the files you may change and,
after a rejected attempt, why it was rejected. The card is your whole task:
follow its Steps and Checklist, change only its files, and work only in the
printed worktree. The card specifies the change and holds no implementation:
you write the tests and the code, reading the repository as you need. Run every
`done_when` command until all pass.

Builds here can run longer than your shell tool waits. Run them in the
foreground with its longest timeout, and never end your turn while one runs:
gc restarts a session that sits idle at its prompt while it holds this step,
and the restart kills the build. If a command must outlast one tool call, start
it detached with its output in a file, then wait for it in the foreground in
calls shorter than the tool's limit.

Finish with exactly one of these, then exit:

    gc superpowers-lite attempt-finish --summary "<what you changed and why>"
    gc superpowers-lite attempt-finish --blocked "<what stops you>"

Do not commit, push, or touch beads; attempt-finish commits for you.
