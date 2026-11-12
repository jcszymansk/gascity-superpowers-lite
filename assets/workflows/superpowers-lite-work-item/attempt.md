Do the task card. Run:

    gc superpowers-lite attempt-start

It resets the worktree, then prints the card, the files it expects you to
change and, after a rejected attempt, why it was rejected. The card is your
whole task: follow its Steps and Checklist, change the files it lists, and work
only in the printed worktree. If the work truly needs another file (a caller of
a renamed method, a fixture), change it and say in your summary which file and
why; the reviewer judges it. Never touch a file only to improve it. The card
specifies the change and holds no implementation: you write the tests and the
code, reading the repository as you need. Run every `done_when` command until
all pass.

Run every build and test command, `done_when` included, through:

    gc superpowers-lite run '<command>'

It runs the command in the worktree, in a process that survives this session,
and prints the exit status and the output's tail. When the command takes
longer than two minutes it says it is still running: run the same line again
at once, and keep doing so until it prints the exit status. Never end your
turn while a command runs, and never leave a command in the background to wait
for it: gc restarts a session that sits idle at its prompt while it holds this
step. If this session is a restarted one, attempt-start says so and keeps the
work already in the worktree.

Finish with exactly one of these, then exit:

    gc superpowers-lite attempt-finish --summary "<what you changed and why>"
    gc superpowers-lite attempt-finish --blocked "<what stops you>"

Do not commit, push, or touch beads; attempt-finish commits for you.
