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
| `superpowers-lite-work` | none | Bugfixes and small changes with no build plan: drain a convoy of work beads. Sling this. |
| `superpowers-lite-work-item` | none | One work bead: a task card, a T1 attempt and its verify step. Internal. |
| `superpowers-lite-next` | none (expansion) | What follows a verify step: a T2 attempt, a human-approved T3 attempt, or land. Internal. |

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
- **`python3` 3.11 or later** on the agents' `PATH`, for the pack commands that run
  `superpowers-lite-work` (standard library only).

## Usage

Import the pack where the formulas should be visible, for example at city scope in `pack.toml`:

```toml
[imports.superpowers-lite]
source = "https://github.com/jcszymansk/gascity-superpowers-lite"
version = "sha:<commit>"
```

The repository has no release tags yet, so pin a commit. While editing the pack, point `source` at
a local clone instead, as described below.

Then run `gc import install`, create a target bead, and sling:

```sh
gc sling <rig>/gc.run-operator <bead> --on superpowers-lite-build \
  --var artifact_root=$GC_CITY/.gc/artifacts/<rig>/<name>/build \
  --var drain_policy=separate
```

A local-path import (`source = "/path/to/gascity-superpowers-lite"`, written into the TOML by hand,
with no `version`) is read in place, so edits to the clone take effect on the next formula compile,
including drains that are already running.

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
gc sling <rig>/superpowers-lite.operator <convoy> --on superpowers-lite-work
```

Each bead becomes one item, run by the pack's own agents, each step in a fresh session:

1. `operator` creates the item's worktree at `$GC_CITY/.gc/worktrees/<rig>/<bead>`.
2. `card-cutter` turns the bead into one task card: the files the change may touch, the code it
   depends on, numbered steps, and `done_when` commands that pass only when the work is done. The
   card is validated, and the checklist for its kind (`bugfix` or `tdd-feature`, from
   `assets/kinds/`) is pasted in.
3. `executor-t1` does the card in the worktree. The pack command it finishes with commits the work.
4. `card-reviewer` runs the checks, then reviews the diff against the card. The checks fail an
   attempt that leaves uncommitted changes, changes nothing, touches a file outside the card,
   deletes or skips a test, or fails a `done_when` command.
5. An approved attempt lands. A rejected one escalates: the worktree is reset to its base and
   `executor-t2` gets the card plus the findings and diff of the failed attempt. A rejected T2
   attempt mails `human` and waits for approval of a T3 attempt (see "Approving a T3 attempt").
   A rejected T3 attempt fails the item.
6. `operator` lands the attempt on the item's target branch and closes the bead.

The target branch is the bead's `target` metadata, else the convoy's, else `lite/<bead id>`. The
default branch is never a target; merging stays a human step. The worktree starts from the target
branch if it exists, otherwise from the default branch. Land moves the target by compare-and-swap
and refuses when the target moved since the item started. A drain runs its items at once, so beads
that share a target must be ordered with `blocks` edges (`gc bd dep add <later> <earlier> --type
blocks`); beads with their own `lite/<id>` targets need no ordering.

The work bead records the outcome: `lite.kind`, one `lite.attempt.<tier>` entry per attempt
(`approved` or the check or review finding that rejected it), `lite.passed_tier`, and
`lite.result` (`landed`, `blocked`, `uncuttable` or `land-refused`). Cards, reports, diffs and
findings are kept under `$GC_CITY/.gc/artifacts/<rig>/superpowers-lite/<bead>/`.

### Approving a T3 attempt

T3 runs on the most expensive slot, so it waits for a person. The mail names the command:

```sh
gc superpowers-lite approve --rig <rig> <bead>
```

It closes the item's approval gate and needs no agent environment. Leave the mail alone to keep
the item waiting.

### Agents and model slots

The agents name only model slots, providers declared in `pack.toml`, so a city moves an agent to
another model or harness by redefining its slot under the same name in `city.toml`:

| Agent | Slot | Default model |
|---|---|---|
| `operator` | `lite-ops` | as `lite-t1` |
| `card-cutter` | `lite-plan` | as `lite-t3` |
| `executor-t1`, `card-reviewer` | `lite-t1` | `claude-haiku-5-5`, effort medium |
| `executor-t2` | `lite-t2` | `claude-sonnet-5`, effort high |
| `executor-t3` | `lite-t3` | `claude-opus-5-5`, effort high |

```toml
[providers.lite-t1]
base = "builtin:pi"
option_defaults = { model = "opencode-go/deepseek-v4.1-flash" }
```

`lite-review` and `lite-review-cross` are declared for later phases. A city-scope import puts the
agents in every rig; rigs need no import of their own.

### Pack commands

Agents never run `bd`, `git commit` or `git push`, and never type a bead id. Each step's text names
`gc superpowers-lite <command>`, which finds the agent's claimed step, does the work, records the
result and closes the step: `claim`, `prepare-worktree`, `cut-card-start`, `cut-card-finish`,
`attempt-start`, `attempt-finish`, `verify`, `verdict`, `approval`, `land` and `close-anchor`.
The code is in `assets/litetools/`; every command logs to
`$GC_CITY/.gc/runtime/superpowers-lite/commands.log`.

Tests: `uv sync`, then `uv run pytest` and `uv run mypy`. `tests/step-blocks.test.sh` runs the
commit-docs block, cut from its step text, against a throwaway repository.

### Calibration cards

`calibration/<rig>/<slug>/` holds cards rebuilt from real commits, for replaying against
different slot bindings (the calibration formula comes in a later phase). `source.toml` names the
base commit, the solution commit and its test files. Each card's first `done_when` command fails
at the base with the solution's tests added and passes at the solution. The first four come from
simpletracker: `time-input`, `entry-draft` and `set-time-worked` (`tdd-feature`), and
`import-token-scan` (`bugfix`, the hardest, a hand-written tokenizer).

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
