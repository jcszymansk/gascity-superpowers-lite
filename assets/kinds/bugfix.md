1. Reproduce the bug first: write or extend a test that fails for the reason the Goal describes, and run it to see it fail.
2. Fix the cause the Context points at, not the symptom. Change nothing the fix does not need.
3. Run the new test again and see it pass, then run every command under `done_when`.
4. Keep every existing test. Do not delete, weaken or skip one to make the suite pass.
5. If the bug is not where the card says, or the fix needs a file the card does not list, stop and report the task as blocked with what you found.
