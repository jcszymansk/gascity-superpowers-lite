Check the attempt and review it. Run:

    gc superpowers-lite verify

It runs the mechanical checks (report, clean worktree, non-empty diff, files
in scope, no skip markers, every `done_when` command). If any fails, it rejects
the attempt and closes this step itself; exit.

If every check passes, it prints the card, the diff and the executor's report,
and lists any tests the attempt removes. Read them and judge whether the diff
does what the card asks and nothing else. A removed test is fine only when the
card asks for its removal or the diff deletes or replaces the code it tested.
Record your verdict with exactly one of:

    gc superpowers-lite verdict approve
    gc superpowers-lite verdict reject --reason "<each problem, with file and line>"

Then exit. Do not change code.
