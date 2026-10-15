Land the reviewed item on its target branch. Ref bookkeeping only: do not
edit, commit, rebase, merge or push, and do not move any ref yourself outside
the block below. Never close the source anchor from this step.

1. Read `gc.root_bead_id` from this step bead as `ITEM_ROOT`. Resolve the
   source anchor as the worktree step did and read its `work_dir` (`WT`),
   `target` (`TARGET`) and `lite.base_commit` (`BASE`); fail if any is missing.
2. Run, with the values filled in. Exit 1 means refused, with the reason on
   stdout and nothing changed.

   ```sh
   set -euo pipefail
   cd "$GC_RIG_ROOT"
   no() { echo "refused: $*"; exit 1; }
   R=$(gc bd list --metadata-field "gc.root_bead_id=$ITEM_ROOT" \
     --metadata-field gc.step_ref=superpowers-lite-work-item.task-review \
     --status closed --all --include-ephemeral --limit 0 --json)
   [ "$(echo "$R" | jq length)" = 1 ] || no "expected one closed task-review step"
   [ "$(echo "$R" | jq -r '.[0].metadata["gc.outcome"] // ""')" = pass ] || no "task review did not pass"
   [ -z "$(git -C "$WT" status --porcelain --untracked-files=all)" ] || no "worktree $WT is not clean"
   HEAD=$(git -C "$WT" rev-parse --verify 'HEAD^{commit}')
   git merge-base --is-ancestor "$BASE" "$HEAD" || no "HEAD does not descend from base $BASE"
   if OLD=$(git rev-parse --verify -q "refs/heads/$TARGET^{commit}"); then
     if [ "$OLD" = "$HEAD" ] || git merge-base --is-ancestor "$HEAD" "$OLD"; then
       echo "nothing to move: $TARGET at $OLD already contains $HEAD"
     else
       git merge-base --is-ancestor "$OLD" "$HEAD" || no "$TARGET moved to $OLD, which HEAD lacks; a sibling landed first"
       git worktree list --porcelain | grep -qx "branch refs/heads/$TARGET" && no "$TARGET is checked out"
       git update-ref -m "land $ITEM_ROOT" "refs/heads/$TARGET" "$HEAD" "$OLD"
       echo "fast-forwarded $TARGET from $OLD to $HEAD"
     fi
   elif [ "$HEAD" = "$BASE" ]; then
     no "the item made no commit and $TARGET does not exist"
   else
     git update-ref -m "land $ITEM_ROOT" "refs/heads/$TARGET" "$HEAD" ""
     echo "created $TARGET at $HEAD"
   fi
   [ "$(git rev-parse "refs/heads/$TARGET")" = "$HEAD" ] || git merge-base --is-ancestor "$HEAD" "refs/heads/$TARGET" || no "$TARGET does not contain $HEAD after landing"
   echo "LANDED=$HEAD"
   ```

   An approved item that made no commit (a spike, say) lands as "nothing to
   move" when `TARGET` already contains its base.
3. Exit 0: set `lite.landed_commit=<LANDED>` on the source anchor and close this
   step with `gc.outcome=pass` and the output as the reason. Otherwise close it
   with `gc.outcome=fail` and the output as the reason. Never retry by other
   means.
