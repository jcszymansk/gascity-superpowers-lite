Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

1. Read current step bead metadata and get `gc.root_bead_id`; hard-fail if it is
   missing. Read that do-work root with `gc bd show <root-bead-id> --json`. If
   `gc bd show --json` returns a one-element list, unwrap the first element before
   reading metadata.
2. Resolve `<source-anchor-id>` from the do-work root:
   - read root metadata `gc.input_convoy_id`; hard-fail if it is missing
   - verify `gc.input_convoy_id` matches rendered runtime convoy `{{convoy_id}}`
   - read that input convoy with `gc bd show <input-convoy-id> --json`; unwrap a
     one-element list response before reading metadata
   - if input convoy metadata has `gc.synthetic_kind=drain-unit-convoy`, use
     input convoy metadata `gc.drain_member_id`
   - do not use the synthetic drain-unit convoy id as `<source-anchor-id>`;
     hard-fail if the selected source anchor id equals the synthetic input convoy id
   - otherwise use `<input-convoy-id>` as the source anchor
   - if root metadata also has `gc.drain_member_id`, it must match the selected
     drain member
3. Validate context path {{context_path}}, files ownership, and verification
   policy for the resolved source anchor.
4. Create or reuse a deterministic git worktree at
   `$GC_CITY/.gc/worktrees/$GC_RIG/<source-anchor-id>`, where gc's closed-bead
   worktree reaper finds and removes it once the source anchor is closed and the
   tree is idle, clean and fully merged. Hard-fail if `GC_CITY`, `GC_RIG` or
   `GC_RIG_ROOT` is empty; never fall back to `$(pwd)/worktrees`. Run every git
   command from the rig repository: `cd "$GC_RIG_ROOT"` first. Base the worktree on the up-to-date
   remote default branch, never the launcher's local `HEAD`, which may be behind
   `origin`. If the path is missing:
   - Resolve the remote default branch (do not hardcode `main`). Read the
     local ref first, and only touch the network if it is missing:

     ```sh
     DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
     if [ -z "$DEFAULT_BRANCH" ]; then
       git remote set-head origin --auto >/dev/null 2>&1 || true
       DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
     fi
     ```

     If it is still empty, fail closed; do not fall back to local `HEAD`.
   - Fetch it so the base is current:
     `git fetch --prune origin "$DEFAULT_BRANCH"`.
   - Create the parent directory and the worktree, detached at the freshly
     fetched tip:

     ```sh
     WORKTREE="$GC_CITY/.gc/worktrees/$GC_RIG/<source-anchor-id>"
     mkdir -p "$(dirname "$WORKTREE")"
     git worktree add "$WORKTREE" --detach "origin/$DEFAULT_BRANCH"
     ```

   If the path exists but is not a worktree of this repository, fail closed.
5. Persist the absolute path on the source anchor with
   `gc bd update <source-anchor-id> --set-metadata work_dir=<absolute worktree path>`.
   For synthetic drain-unit convoys, never persist `work_dir` on the synthetic drain-unit convoy; the original drain member/source anchor is authoritative.
   Verify the source anchor now has `work_dir` before closing this step with
   `gc.outcome=pass`.
