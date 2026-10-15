Resolve the target branch and create the isolated worktree for this item.
Infrastructure only: do not edit source files in the launcher checkout. Run
every git command from the rig repository (`cd "$GC_RIG_ROOT"`); hard-fail if
`GC_CITY`, `GC_RIG` or `GC_RIG_ROOT` is empty. `gc bd show --json` returns an
object or a one-element list; handle both.

1. Read `gc.root_bead_id` from this step bead and read that root. Its
   `gc.input_convoy_id` must equal `{{convoy_id}}`. If that convoy has
   `gc.synthetic_kind=drain-unit-convoy`, the source anchor is its
   `gc.drain_member_id` and the parent convoy is its `gc.parent_convoy_id`;
   otherwise the source anchor is the convoy itself and there is no parent.
   Hard-fail if the source anchor id equals a synthetic convoy id.
2. Resolve the default branch: with an `origin` remote, the branch of
   `refs/remotes/origin/HEAD` (run `git remote set-head origin --auto` once if
   it is missing), then `git fetch --prune origin "$DEFAULT_BRANCH"` and fail
   closed if the fetch fails; without a remote, the rig's `default_branch` from
   `gc --city "$GC_CITY" rig list --json | jq -r --arg rig "$GC_RIG" '.rigs[] | select(.name == $rig) | .default_branch // empty'`.
   Fail closed if it is empty.
3. `TARGET` is the source anchor's `target` metadata, else the parent convoy's
   `target`, else `lite/<source-anchor-id>`. Fail closed if `TARGET` equals the
   default branch: only a human merges into it.
4. `BASE` is `refs/heads/$TARGET` if that branch exists, so items on a shared
   target stack; otherwise `origin/$DEFAULT_BRANCH` with a remote, or
   `refs/heads/$DEFAULT_BRANCH` without one. Fail closed if `BASE` does not
   resolve to a commit. Log `TARGET`, `BASE` and its commit.
5. Create the worktree detached at `BASE` where gc's closed-bead worktree
   reaper finds it:

   ```sh
   WORKTREE="$GC_CITY/.gc/worktrees/$GC_RIG/<source-anchor-id>"
   mkdir -p "$(dirname "$WORKTREE")"
   git worktree add "$WORKTREE" --detach "$BASE"
   ```

   If the path exists and is a worktree of this repository whose `HEAD` is the
   recorded `lite.base_commit` or descends from it, reuse it. Otherwise fail
   closed.
6. On the source anchor, never on a synthetic convoy, set `work_dir=<absolute
   worktree path>`, `target=<TARGET>` and `lite.base_commit=<commit of BASE>`
   (keep an existing `lite.base_commit` when reusing). Read them back, then close
   this step with `gc.outcome=pass`.
