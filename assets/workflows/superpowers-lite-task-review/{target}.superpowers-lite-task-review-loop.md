Run the single-reviewer Superpowers task review loop.

The review lane reads the task diff once and reports a spec-compliance verdict
and a code-quality verdict. The apply lane is the only child that sets
`code_review.verdict=done|iterate` and `code_review.report_path`. The
implementation review check repeats this loop at most once, and only when the
apply lane sets `code_review.verdict=iterate`.

Do not invoke provider-native subagents. Re-run or continue only through this
Gas City graph loop.
