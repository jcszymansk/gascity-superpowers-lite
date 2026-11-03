# superpowers-lite

A Gas City pack that runs the [superpowers](https://github.com/gastownhall/gascity-packs/tree/main/superpowers)
build pipeline with a cheaper per-task review. Brainstorming, the written spec, the plan, plan
review, decomposition, per-task TDD and the final code-review fan-out are superpowers' own. Only the
review after each task changes:

| | superpowers | superpowers-lite |
|---|---|---|
| Reviewers per task | two: spec compliance, then code quality | one, returning both verdicts in one pass |
| Fix rounds per task | up to 6 review loops | the implementer fixes once; a second review runs only if it could not clear every required finding |
| Lasting documents | stay with the other artifacts | requirements, design and final report are committed to the integration branch (see "Build documents") |

## Formulas

| Formula | Extends | Use |
|---|---|---|
| `superpowers-lite-build` | `superpowers-build` | The whole pipeline, from brainstorming to publish. Sling this. |
| `superpowers-lite-implementation` | `superpowers-implementation` | Drain an already approved convoy only, without planning. |
| `superpowers-lite-development` | `superpowers-development` | One task in its own session and worktree (`drain_policy=separate`). |
| `superpowers-lite-development-item` | `superpowers-development-item` | One task in a shared session (`drain_policy=same-session`). Internal. |
| `superpowers-lite-task-review` | none (expansion) | The single-reviewer task review loop. |
| `superpowers-lite-work` | gascity `implement` | Bugfixes and small changes with no build plan: drain a convoy of work beads. Sling this. |
| `superpowers-lite-work-item` | `superpowers-lite-development` | One work bead: TDD, the single-reviewer review, land on its target branch. Internal. |

Apart from `docs_dir`, all variables are superpowers' own; see its README.
`implementation_formula` and `implementation_item_formula` default to the lite formulas.
`brainstorming_approval_mode` defaults to `interactive` instead of superpowers' `autonomous`, so
`superpowers-lite-build` mails `human` and waits for approval of the design and again of the
written spec. Pass `--var brainstorming_approval_mode=autonomous` to let agents approve them.

## Requirements

- **The superpowers pack at `390cac1a`.** This pack imports it (`pack.toml`). Lite overrides
  superpowers steps by id and replaces them whole, so a different superpowers revision can silently
  drop or duplicate steps. Bump both together, and recompile every lite formula after a bump.
- **Rig imports.** Each rig that runs lite needs superpowers and `gascity/roles` imported, as
  superpowers itself requires, plus the check scripts in `<rig>/.gc/scripts/`. Lite routes to
  `gc.run-operator`, `superpowers.code-quality-reviewer` and the `implementation_target` role.
- **`[daemon] auto_reap_closed_bead_worktrees = true`** in `city.toml`, for
  `drain_policy=separate`. See "Task worktrees".
- **`jq`** on the agents' `PATH`, and for rigs without an `origin` remote, a `default_branch` in
  the rig's `city.toml` entry. See "Task worktrees".

## Usage

Import the pack where the formulas should be visible, for example at city scope in `pack.toml`:

```toml
[imports.superpowers-lite]
source = "/path/to/gascity-superpowers-lite"
```

then `gc import install`, create a target bead, and sling:

```sh
gc sling <rig>/gc.run-operator <bead> --on superpowers-lite-build \
  --var artifact_root=$GC_CITY/.gc/artifacts/<rig>/<name>/build \
  --var drain_policy=separate
```

A local-path import is read in place, so edits to this repo take effect on the next formula
compile, including drains that are already running.

To switch a running superpowers build to lite at implementation, let it finish spec approval,
retire it, and sling `superpowers-lite-build` with `requirements_path` set to the approved spec.

Keep `artifact_root` outside the rig repository. The artifacts (reviews, logs, per-task evidence)
are not code, and an agent that finds them inside the repository tends to commit them, often to
the default branch and apart from the code they describe.

## Work beads (no build plan)

`superpowers-lite-build` suits a feature: brainstorming, a spec, a plan and decomposition before any
code. For a bugfix or a small change to an existing project, write the bead itself as the
specification (description and acceptance criteria), put it in a convoy and sling
`superpowers-lite-work`:

```sh
gc convoy create <name> <bead>...            # optionally --target <branch>
gc sling <rig>/gc.run-operator <convoy> --on superpowers-lite-work
```

Each bead runs `superpowers-lite-work-item` in its own session and worktree: superpowers' TDD
steps, the single-reviewer task review, a commit with a `Bead: <id>` trailer, then a land step.
The bead lands on its target branch: the bead's `target` metadata, else the convoy's, else
`lite/<bead id>`. The default branch is never a target; merging stays a human step. The worktree
starts from the target branch if it exists, otherwise from the default branch.

The land step's commands are inlined in its step text, since a pack cannot point agents at its
own scripts. It refuses unless the item's task review passed, the worktree is clean, and the
target can be fast-forwarded to the item by compare-and-swap. An approved item with no commit
lands as "nothing to move". A separate drain runs its items at once, so beads that share a target
must be ordered with `blocks` edges (`gc bd dep add <later> <earlier> --type blocks`); without
them, every item after the first is refused at land. Beads with their own `lite/<id>` targets
need no ordering. Only `drain_policy=separate` is supported.

`tests/step-blocks.test.sh` runs the land and commit-docs blocks, cut from their step texts,
against a throwaway repository.

## Build documents

`superpowers-lite-build` adds a `commit-docs` step between `finalize` and `publish`. It reads the
integration branch from `gc.build.finalize_head` and commits the approved requirements, the design
and the final report to it, under `<docs_dir>/<workflow root id>/` (`docs_dir` defaults to
`docs/build`). The commit carries a `Bead: <id>` trailer for each source bead, so the documents
merge together with the code and `publish` pushes both. The step moves the branch by
compare-and-swap and fails, leaving the branch alone, if `finalize` merged or moved it.

## How the borrowed step texts resolve

Six lite steps reuse prose from other packs: the two `implement` steps and `publish` of
`superpowers-lite-build`, the two `drain-*` steps of `superpowers-lite-implementation`, and the
finalize step of `superpowers-lite-task-review`. They point at `../assets/workflows/superpowers-*/...`
or `../assets/workflows/build-base/...`, paths that do not exist in this repo. That is intended: per
the Gas City formula spec, a `../assets/...` path resolves through the same layer order as the
formula itself, so it finds the superpowers or gascity pack's file. An override step must name its
`description_file` again, because a child step replaces the parent step whole and inherits none of
its fields. An unresolvable path fails at compile time.

## Task worktrees

`superpowers-lite-development` replaces the `prepare-worktree` step it inherits from gascity's
`do-work`. Upstream creates each task worktree at `<rig>/worktrees/<id>` and nothing ever removes
it; on one rig that was 29 worktrees and 3.2 GB after about 30 tasks. Lite creates it at
`$GC_CITY/.gc/worktrees/$GC_RIG/<id>`, the only place gc's closed-bead worktree reaper looks, so the
reaper removes it once the task is closed and the tree is idle, clean and merged.

The worktree never starts from the launcher's `HEAD`. If the rig has an `origin` remote, it starts
from a freshly fetched `origin/<default branch>`, and a failed fetch stops the task. If the rig has
no remote at all, it starts from the local branch named by the rig's `default_branch`.

Remove this override once [gastownhall/gascity-packs#510](https://github.com/gastownhall/gascity-packs/issues/510)
is fixed upstream.

## Origin

Written in the gcexp city on 2026-10-11 and 2026-10-12 and moved here unchanged from gcexp commit
`45db1cb`.
