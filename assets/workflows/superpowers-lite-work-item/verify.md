Check the attempt and review it. Run:

    gc superpowers-lite verify

It runs the mechanical checks (report, clean worktree, non-empty diff, no skip
markers, every `done_when` command). If any fails, it records the verdict and
closes this step itself; exit.

The `done_when` commands run in the background and can take most of an hour.
While they run, verify waits under two minutes and then says they are still
running: run it again at once, and keep doing so until it prints a result.
Never end your turn while they run, and never leave verify in the background
to wait for it: gc restarts a session that sits idle at its prompt while it
holds this step. A restarted session's verify picks up the same checks.

If every check passes, it prints the card, the diff and the executor's report,
and lists any tests the attempt removes and any files it changes that the card
does not list. Read them and judge whether the diff does what the card asks and
nothing else. A removed test is fine only when the card asks for its removal or
the diff deletes or replaces the code it tested. An unlisted file is fine only
when the change needs it and the report says why.
Record your verdict with exactly one of:

    gc superpowers-lite verdict approve
    gc superpowers-lite verdict correct --reason "<each problem, with file and line>"
    gc superpowers-lite verdict restart --reason "<why the attempt cannot be fixed>"

Approve a diff that does what the card asks and nothing else. Ask to correct
one that is close: the next round continues from it and fixes what you name.
Restart one that fixing would mean starting over: its approach contradicts the
card, fixing it would discard most of the diff, it spreads into files the
change does not need, or your findings repeat what an earlier round of the
same attempt already named. The next attempt starts from the card's base.

Then exit. Do not change code.
