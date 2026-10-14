Review one Superpowers task: first whether it matches its requirements, then
whether it is well built. This is a task-scoped gate. A whole-branch review
runs separately after all tasks are complete, so do not review the branch.

Inputs:

- Resolve the source anchor (the drained task bead) the same way the inherited
  worktree setup does, read its `work_dir`, and `cd` there. Never review the
  launcher checkout.
- Read the task bead, then the approved plan at the task bead's
  `gc.build.plan_path`, section `gc.build.plan_task`, and the requirements at
  `gc.build.requirements_path`. Read the plan's global constraints if it has
  them.
- Read the implementer's task summary (`gc.implementation.summary_path` on the
  item workflow root). Treat it as unverified claims, including any design
  rationale ("kept simple on purpose" does not lower a finding's severity).
- Compute the task diff once, from the commit before the task's first commit
  to `HEAD` (`git diff --stat` and `git diff`), or `git diff HEAD` plus the
  task commits if the change is not committed yet. Write it to the task
  artifact directory and review that file. Read code outside the diff only to
  check a concrete risk you name in the report.

Rules:

- Read-only. Do not edit files, stage, commit, check out, or reset anything.
- Do not re-run the full test suite. Run one focused test only when the code
  raises a doubt that the implementer's recorded evidence does not answer.
- Do not dispatch subagents or ask for a second opinion.
- Back every finding with a file and line. Mark each finding `required` (spec
  gap, defect, missing or vacuous test, broken constraint) or `optional`.
- If a requirement depends on code the diff does not touch and you cannot
  verify it from the diff, say so explicitly instead of guessing.

Write one report under the task artifact directory with two sections, Spec
Compliance and Code Quality, each ending in `approve` or `iterate`.

Close with `gc.outcome=pass`,
`code_review.task_verdict=approve|iterate` (iterate if either section does),
`code_review.task_report_path=<report path>`, and
`code_review.output_path=<report path>`.

Do not set `code_review.verdict` or `code_review.report_path`; the apply lane
owns those approval-check fields.
