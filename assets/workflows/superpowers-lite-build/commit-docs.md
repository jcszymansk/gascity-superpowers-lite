Commit the build's lasting documents (requirements, design, final report) to
its integration branch, next to the code they describe, so they merge with it.
This step is mechanical: do not edit the documents, and move no ref other than
the integration branch.

1. Read `gc.root_bead_id` from this step bead as `ROOT`. From `ROOT`'s metadata
   read `gc.build.finalize_head` (`<branch>@<commit>`, giving `BRANCH` and
   `COMMIT`), `gc.build.requirements_path`, `gc.build.design_path` and
   `gc.build.final_report_path`. `gc bd show --json` returns an object or a
   one-element list; handle both. Read the beads tracked by convoy
   `{{convoy_id}}`: those are the source beads. Fail this step if a value is
   missing, a path is not a readable file, or `refs/heads/$BRANCH` in
   `$GC_RIG_ROOT` is not `COMMIT` (finalize merged or moved the branch).
2. Run, with the values filled in:

   ```sh
   set -euo pipefail
   cd "$GC_RIG_ROOT"
   if git worktree list --porcelain | grep -qx "branch refs/heads/$BRANCH"; then
       echo "$BRANCH is checked out in a worktree"; exit 1
   fi
   WT="$(mktemp -d)/docs"
   trap 'git worktree remove --force "$WT" 2>/dev/null || true' EXIT
   git worktree add -q --detach "$WT" "$COMMIT"
   DEST="{{docs_dir}}/$ROOT"
   mkdir -p "$WT/$DEST"
   cp "$REQUIREMENTS" "$WT/$DEST/requirements.md"
   cp "$DESIGN" "$WT/$DEST/design.md"
   cp "$FINAL_REPORT" "$WT/$DEST/final-report.md"
   git -C "$WT" add -f "$DEST"
   git -C "$WT" commit -q -m "$SUBJECT" -m "$BODY" -m "$TRAILERS"
   NEW="$(git -C "$WT" rev-parse HEAD)"
   git update-ref -m "docs of $ROOT" "refs/heads/$BRANCH" "$NEW" "$COMMIT"
   ```

   `add -f` because ignore rules such as `build/` can match `{{docs_dir}}`.
   Write `SUBJECT` in the repository's commit style, for example
   `docs: add the requirements, design and final report of build <ROOT>`.
   `BODY` says these are the lasting documents of workflow `ROOT` and that its
   other artifacts stay under `{{artifact_root}}`. `TRAILERS` holds one
   `Bead: <id>` line per source bead.
3. Set `gc.build.docs_commit=<NEW>` and `gc.build.docs_path=<DEST>` on `ROOT`,
   then close this step with `gc.outcome=pass`.

On any failure, leave the branch as it was (the block removes its own
worktree) and close this step with `gc.outcome=fail` and the error as the
reason. Never commit the documents anywhere else, and never commit any other
artifact.
