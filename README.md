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

1. `operator` creates the item's worktree at `$GC_CITY/.gc/worktrees/<rig>/<bead>` and records
   the item's ladder budget (see `docs/design/lite-v2.md`, "Configuring the budget").
2. `card-cutter` turns the bead into task cards: the files the change may touch (paths or
   `*`/`**` patterns, any number; files an attempt changes beyond them go to the reviewer), the existing
   code it depends on, numbered steps, and `done_when` commands that pass only when the work is
   done. A card is sized by the design it must settle, typically half a day of a competent
   developer's work once settled, not by time or file count. A bead larger than that is cut into
   up to 10 cards, done in order; `--blocked` (`lite.result = uncuttable`) is for a bead that is
   unclear or needs a human decision. A card holds no implementation or test code. The validator allows code blocks only in
   `## Interfaces` (up to 40 lines of signatures) and `## Context`, whose lines must exist in the
   repository. The checklist for the card's kind (`bugfix`
   or `tdd-feature`, from `assets/kinds/`) is then pasted in. `cut-card-start` prints a worked
   example card (`assets/templates/card-example.md`), and the step text keeps the cutter to the
   bead and the worktree at `HEAD`, because cutters otherwise go looking for earlier cards and
   solutions on disk. `cut-card-finish` runs the first card's `done_when` at `HEAD` and refuses a
   command that fails there unless the card's `## Baseline` says why (the test it runs is new in
   the card); a later card gets the same check on its own base before its first attempt.
3. `executor-t1` does the first card in the worktree. The pack command it finishes with commits the work,
   with a `Bead: <id>` trailer.
4. The card reviewer of the attempt's tier (`card-reviewer-t1`, `-t2` or `-t3`) runs the checks,
   then reviews the diff against the card. The checks fail an
   attempt whose report is missing, whose executor reported a blocker, or that leaves uncommitted
   changes, changes nothing, adds a skip marker or fails a `done_when` command. Files outside the
   card and removed tests are listed for the reviewer to judge.
5. The reviewer approves, asks to correct, or restarts; failed checks count as correct, or as
   restart when the same check also failed the previous round. An approved attempt on a card with
   cards after it starts the next card at T1, from the approved commit; an approved attempt on the
   last card lands. Correct runs the next round of the same attempt, from its commit and with its
   findings, while the tier's budget has rounds left; restart, or correct in the last round, starts
   the next attempt from where the card started, with every earlier round's findings and the last
   diff as context. With no attempts left the card escalates to `executor-t2`, then, after a mail
   to `human` and an approval, to `executor-t3` (see "Approving a T3 attempt"); a later T3 round or
   attempt needs no second approval. An executor that reports a blocker in the work
   (`--blocker work`) escalates at once; a blocker in the card (`--blocker card`, or a later card
   failing its base check) fails the item at once with a mail to `human`, since every tier would
   get the same card. When
   T3's budget runs out the item fails and `human` gets a mail with the findings. Each tier's
   budget is set below.
6. `operator` lands every card's work on the item's target branch at once and closes the bead.

The target branch is the bead's `target` metadata, else the convoy's, else `lite/<bead id>`. The
default branch is never a target; merging stays a human step. The worktree starts from the target
branch if it exists, otherwise from the default branch, with its submodules checked out (from the
rig's own submodule clones where it has them). Land moves the target by compare-and-swap and refuses
when the target moved since the item started. A drain runs its items at once, so beads that share a
target must be ordered with `blocks` edges (`gc bd dep add <later> <earlier> --type blocks`); beads
with their own `lite/<id>` targets need no ordering.

A failure ends the item without sending agents to steps that can only refuse. The item's steps
form one gc scope with `gc.on_fail = "abort_scope"`: when one closes failed (a worktree that
cannot be prepared, an uncuttable bead, a blocked verify), gc skips the steps still waiting,
including those verify bonded at runtime, and the item fails. A failed item does not stop the
drain, but its `blocks` successors do not run on a target that lacks it: prepare-worktree fails
an item whose predecessor is not closed, or closed with a `lite.result` other than `landed`, and
records `lite.result = skipped`. A predecessor a human closed without lite counts as done.

The work bead records the outcome: `lite.cards` and the current `lite.card`, `lite.kind` (each
card's kind once, comma-separated), one `lite.attempt.<attempt>` entry per attempt (`t1`, `t1.r2` for round 2,
`t1.a2` for a second attempt, `t2.a2.r3`; `approved`, or `correct: ` or `restart: ` and the check
or review finding), `lite.attempt.<attempt>.failed_checks` when checks failed it,
`lite.last_rejected`, `lite.passed_tier`, `lite.card_overlap.<attempt>` (how many of the attempt's
added lines of 12 or more characters appear verbatim in the card, such as `4/333`),
`lite.files_touched.<attempt>`, per attempt the sessions and slots that executed and reviewed
it with their times (`lite.attempt.<attempt>.executor_sessions`, `.executor_provider`,
`.started_at`, `.finished_at`, `.reviewer_sessions`, `.reviewer_provider`, `.review_started_at`,
`.done_when_seconds`, `.verified_at`), the ladder budget with its source
(`lite.budget.<tier>.attempts`, `lite.budget.<tier>.rounds`, each with a `.source` of `var`, `env`
or `pack`), and `lite.result` (`landed`, `blocked`, `uncuttable`,
`land-refused` or `skipped`). An item of several cards keeps the per-card entries under
`lite.card.<n>.` instead (`lite.card.2.attempt.t1`, `lite.card.2.passed_tier`, and
`lite.card.<n>.base_commit` for where card n starts), and its `lite.passed_tier` is the highest tier
any card needed. Drafts, cards, reports, diffs and findings are kept under
`$GC_CITY/.gc/artifacts/<rig>/superpowers-lite/<bead>/` (`drafts/<n>.md`, `cards/<n>/`).

### Ladder budget

Each tier gets a number of attempts (each starting from where the card starts) and of rounds per
attempt (each continuing the previous round). The pack defaults are T1 1 attempt of 2 rounds, T2
and T3 1 attempt of 1 round. Set any of them, as whole numbers from 1 to 10, highest precedence
first:

```sh
gc sling <rig>/superpowers-lite.operator <convoy> --on superpowers-lite-work --var lite_t1_rounds=3
```

```toml
# city.toml
[[rigs]]
name = "<rig>"
formula_vars = { lite_t1_attempts = "3", lite_t1_rounds = "3" }

[workspace]
env = { LITE_T1_ATTEMPTS = "2", LITE_T2_ROUNDS = "2" }
```

The names are `lite_<tier>_<attempts|rounds>` as formula vars and `LITE_<TIER>_<ATTEMPTS|ROUNDS>`
in the environment. `prepare-worktree` resolves the budget once per item and records it on the
work bead, so a change reaches only items prepared after it; an invalid value fails the item.
A tier runs at most attempts × rounds executor sessions and as many reviews.

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
| `executor-t1` | `lite-t1` | `claude-haiku-5-5`, effort medium |
| `executor-t2` | `lite-t2` | `claude-sonnet-5`, effort high |
| `executor-t3` | `lite-t3` | `claude-opus-5-5`, effort high |
| `card-reviewer-t1` | `lite-card-review-t1` | as `lite-t2` |
| `card-reviewer-t2` | `lite-card-review-t2` | as `lite-t2` |
| `card-reviewer-t3` | `lite-card-review-t3` | as `lite-t3` |

```toml
[providers.lite-t1]
base = "builtin:pi"
option_defaults = { model = "opencode-go/deepseek-v4.1-flash" }
```

The reviewer is the only gate between a cheap executor and the target branch, so T1 work is
reviewed one model up by default. A review reads the card, the diff and the report and runs no
exploration or build of its own, so it costs far less than an attempt on the same model. To have
Haiku review Haiku, point `lite-card-review-t1` back at `lite-t1`. `lite-review` and
`lite-review-cross` are declared for later phases. A city-scope import puts the
agents in every rig; rigs need no import of their own.

### Pack commands

Agents never run `bd`, `git commit` or `git push`, and never type a bead id. Each step's text names
`gc superpowers-lite <command>`, which finds the agent's claimed step, does the work, records the
result and closes the step: `claim`, `prepare-worktree`, `cut-card-start`, `cut-card-finish`,
`attempt-start`, `attempt-finish`, `run`, `verify`, `verdict`, `approval`, `land` and `close-anchor`.
Executors run builds and tests through `run '<command>'`, and `verify` runs `done_when`, in a runner
that outlives the agent's session and is waited for in calls under two minutes, because gc drains
a session that sits idle at its prompt while it holds a step. The code is in `assets/litetools/`; every command logs to
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
