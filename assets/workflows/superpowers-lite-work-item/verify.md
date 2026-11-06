Check the attempt and review it. Run:

    gc superpowers-lite verify

It runs the mechanical checks (report, clean worktree, non-empty diff, files
in scope, tests intact, every `done_when` command). If any fails, it rejects
the attempt and closes this step itself; exit.

If every check passes, it prints the card, the diff and the executor's report.
Read them and judge whether the diff does what the card asks and nothing else.
Record your verdict with exactly one of:

    gc superpowers-lite verdict approve
    gc superpowers-lite verdict reject --reason "<each problem, with file and line>"

Then exit. Do not change code.
