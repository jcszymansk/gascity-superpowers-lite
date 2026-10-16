Apply the Superpowers task review findings.

Make code changes only in the source anchor's `work_dir` worktree. Read the review report from
`code_review.task_report_path`.

- If the review approves both sections, write a no-op task-review summary.
- Otherwise fix every `required` finding with the smallest change, rerun the
  focused verification for the touched behaviour, and record the command and
  result. Apply `optional` findings only when they are trivial and local.
- If you dispute a finding, record the evidence in the summary instead of
  silently skipping it.
- A test the review asks for that pins behaviour the code already has passes
  at once; that is expected. Show it is not vacuous by naming the behaviour
  and inputs it pins in the summary. Never delete, break or revert production
  code, even briefly, to watch it fail.

Set `code_review.verdict=done` when every required finding is fixed and
verified, or disputed with evidence. Set `code_review.verdict=iterate` only
when a required finding is still open after this pass; that triggers one more
review, and a second `iterate` fails the task.

Always close with `gc.outcome=pass`, `code_review.verdict=done|iterate`,
`code_review.report_path=<task review summary path>`, and
`code_review.output_path=<task review summary path>`:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.verdict=done' \
  --set-metadata 'code_review.report_path=<task review summary path>' \
  --set-metadata 'code_review.output_path=<task review summary path>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Superpowers task review applied.'
```

Do not pass freeform notes or extra positional arguments to `gc bd update`.
Do not invoke provider-native subagents.
