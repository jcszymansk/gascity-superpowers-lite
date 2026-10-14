# superpowers-lite

A Gas City pack that runs the [superpowers](https://github.com/gastownhall/gascity-packs/tree/main/superpowers)
build pipeline with a cheaper per-task review. Brainstorming, the written spec, the plan, plan
review, decomposition, per-task TDD and the final code-review fan-out are superpowers' own. Only the
review after each task changes:

| | superpowers | superpowers-lite |
|---|---|---|
| Reviewers per task | two: spec compliance, then code quality | one, returning both verdicts in one pass |
| Fix rounds per task | up to 6 review loops | the implementer fixes once; a second review runs only if it could not clear every required finding |

## Formulas

| Formula | Extends | Use |
|---|---|---|
| `superpowers-lite-build` | `superpowers-build` | The whole pipeline, from brainstorming to publish. Sling this. |
| `superpowers-lite-implementation` | `superpowers-implementation` | Drain an already approved convoy only, without planning. |
| `superpowers-lite-development` | `superpowers-development` | One task in its own session and worktree (`drain_policy=separate`). |
| `superpowers-lite-development-item` | `superpowers-development-item` | One task in a shared session (`drain_policy=same-session`). Internal. |
| `superpowers-lite-task-review` | none (expansion) | The single-reviewer task review loop. |

All variables are superpowers' own; see its README. `implementation_formula` and
`implementation_item_formula` default to the lite formulas.

## Requirements

- **The superpowers pack at `390cac1a`.** This pack imports it (`pack.toml`). Lite overrides
  superpowers steps by id and replaces them whole, so a different superpowers revision can silently
  drop or duplicate steps. Bump both together, and recompile every lite formula after a bump.
- **Rig imports.** Each rig that runs lite needs superpowers and `gascity/roles` imported, as
  superpowers itself requires, plus the check scripts in `<rig>/.gc/scripts/`. Lite routes to
  `gc.run-operator`, `superpowers.code-quality-reviewer` and the `implementation_target` role.
- **`[daemon] auto_reap_closed_bead_worktrees = true`** in `city.toml`, for
  `drain_policy=separate`. See "Task worktrees".
- **An `origin` remote with a default branch**, for `drain_policy=separate`. Each task worktree
  starts from a freshly fetched `origin/<default branch>`, and the step fails closed when there is no
  `origin`.

## Usage

Import the pack where the formulas should be visible, for example at city scope in `pack.toml`:

```toml
[imports.superpowers-lite]
source = "/path/to/gascity-superpowers-lite"
```

then `gc import install`, create a target bead, and sling:

```sh
gc sling <rig>/gc.run-operator <bead> --on superpowers-lite-build \
  --var artifact_root=<rig path>/plans/<name>/build \
  --var drain_policy=separate
```

A local-path import is read in place, so edits to this repo take effect on the next formula
compile, including drains that are already running.

To switch a running superpowers build to lite at implementation, let it finish spec approval,
retire it, and sling `superpowers-lite-build` with `requirements_path` set to the approved spec.

## How the borrowed step texts resolve

Five lite steps reuse superpowers' prose: the two `implement` steps of `superpowers-lite-build`,
the two `drain-*` steps of `superpowers-lite-implementation`, and the finalize step of
`superpowers-lite-task-review`. They point at `../assets/workflows/superpowers-*/...`, paths that do
not exist in this repo. That is intended: per the Gas City formula spec, a `../assets/...` path
resolves through the same layer order as the formula itself, so it finds the superpowers pack's
file. An override step must name its `description_file` again, because a child step replaces the
parent step whole and inherits none of its fields. An unresolvable path fails at compile time.

## Task worktrees

`superpowers-lite-development` replaces the `prepare-worktree` step it inherits from gascity's
`do-work`. Upstream creates each task worktree at `<rig>/worktrees/<id>` and nothing ever removes
it; on one rig that was 29 worktrees and 3.2 GB after about 30 tasks. Lite creates it at
`$GC_CITY/.gc/worktrees/$GC_RIG/<id>`, the only place gc's closed-bead worktree reaper looks, so the
reaper removes it once the task is closed and the tree is idle, clean and merged.

Remove this override once [gastownhall/gascity-packs#510](https://github.com/gastownhall/gascity-packs/issues/510)
is fixed upstream.

## Origin

Written in the gcexp city on 2026-10-11 and 2026-10-12 and moved here unchanged from gcexp commit
`45db1cb`.
