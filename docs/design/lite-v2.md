# superpowers-lite v2: tiered delegation

Status: proposed, 2026-11-06. Applies to superpowers-lite at `23a64c6`, superpowers at `390cac1a`,
gc 1.5.1.

## Goal

Run most of a build on cheap models. Strong models write the requirements, the design and the
plan, and review the result. Cheap models carry out one small, precisely specified task at a time.
Scripts check every cheap result before any model reviews it, and a task that fails moves up one
model tier on its own.

The pack names no model and no harness. A city binds models to the pack's slots in `city.toml`,
so a new model release, a retired model or a change of subscription is a three-line edit there,
and a stranger who imports the pack can bind whatever they have.

## Non-goals

- A catalog of dozens of persona agents. The OpenCode fork reviewed for this design
  (`danbak0757/opencode`) ships 67; 48 of them are a title, one sentence of responsibility and
  shared boilerplate. Specialist knowledge goes into per-task checklists instead (see "Task kinds").
- Agents choosing other agents at run time. gc formulas are static graphs; optional lanes use
  compound-engineering's selector and gate pattern where needed.
- Changing the build-base pipeline. No stage is added, renamed or reordered.

## Evidence behind the design

- **This city's cheap-model failures were about gc, not about code.** Sonnet closed drain item
  roots instead of releasing them (`gcexp/city.toml`, 2026-10-11, nt-38ut), so the implementer
  went back to Opus. A model on simpletracker substituted `{target}` in a prompt path
  (smt-2u6a). City management ran on pi from 2026-10-23 and went back to Claude a week later.
  Cheap agents therefore never touch bead lifecycle in v2.
- **superpowers plans are already written for an executor with no context.** `writing-plans`
  asks for exact file paths, complete code in every step and exact commands with expected
  output (`superpowers/skills/writing-plans/SKILL.md:10,117-119`). A task card is mostly a
  self-contained slice of such a plan.
- **Strong planner, cheap editor works elsewhere.** Aider's architect mode with o3 planning and
  GPT-4.1 editing scored 83% on the polyglot benchmark for less than o3 alone. The owner ran a
  similar setup earlier in 2026 with Sonnet planning and gpt-5-mini coding.
- **Cross-family review already runs here.** simpletracker reviews on gpt-6-luna while its
  other roles run on deepseek-v4.1-flash.

## Decisions

| # | Decision |
|---|---|
| D1 | v2 is the next version of superpowers-lite, not a separate pack. It keeps the superpowers import for now (see "Relation to superpowers"). |
| D2 | Lite ships its own agent for every step it controls, each bound to a slot. It stops routing to `superpowers.*` and `gc.*` role agents, which a pack cannot bind to its slots. |
| D3 | Escalation from T1 to T2 runs automatically. Escalation to T3 waits at a human gate until the cost per item is known from calibration. |
| D4 | An escalated attempt starts from a reset worktree. It receives the failed diff and the check output as context, not as a starting point. |
| D5 | Hooks: patch `install_agent_hooks` per city until gc installs hooks for an agent's resolved harness; draft that upstream issue together with a rig-level provider alias. Lite never files them; the owner does. |

## Pipeline

| build-base stage | superpowers-lite v1 | v2 |
|---|---|---|
| prepare | inherited | same |
| requirements | brainstorm and spec loops, human approval | same, on `lite-plan` |
| plan | `writing-plans` | same, with one rule added: every task fits on one card |
| plan-review | superpowers review loop | same, plus one question: can each task go to a cheap model exactly as written? |
| decompose | scope-only task beads pointing into the plan | **one card per task** (see "Task card") |
| implement, per item | TDD implementer, one reviewer, one fix round | **tiered loop** (see "Per-item loop") |
| review | code review and gap-analysis fan-out | same, on `lite-review` and `lite-review-cross` |
| finalize, commit-docs, publish | superpowers and lite | same |

`superpowers-lite-work` keeps its shape: each work bead is converted into a card, then runs the
same per-item loop. A well-written bug bead is already close to a card, so this is the cheapest
route through the pack and the first one to build.

## Model slots

A slot is an ordinary gc provider with a `lite-` name, declared in `pack.toml`. Pack agents name
a slot as their `provider` and set no `option_defaults`, so the slot alone decides harness,
model, effort, flags and upstream.

```toml
# pack.toml: defaults for anyone with a Claude login
[providers.lite-t1]
base = "builtin:claude"
option_defaults = { model = "claude-haiku-5-5", effort = "medium" }

[providers.lite-t2]
base = "builtin:claude"
option_defaults = { model = "claude-sonnet-5", effort = "high" }

[providers.lite-t3]
base = "builtin:claude"
option_defaults = { model = "claude-opus-5-5", effort = "high" }

[providers.lite-plan]         # requirements, design, plan, card cutting
base = "provider:lite-t3"
[providers.lite-review]       # whole-branch review
base = "provider:lite-t3"
[providers.lite-review-cross] # second-opinion review, ideally another model family
base = "provider:lite-t3"
[providers.lite-ops]          # operator chores, selectors, gates
base = "provider:lite-t1"
```

A city overrides a slot by defining a provider with the same name:

```toml
[providers.lite-t1]
base = "builtin:pi"
option_defaults = { model = "opencode-go/deepseek-v4.1-flash" }
args_append = ["--thinking", "high"]
```

### Behaviour verified on gc 1.5.1

Checked in a scratch city with a rig-imported test pack, using `gc config explain` and a Go test
that builds launch commands with gc's own `ResolveProvider` and `BuildProviderLaunchCommand`:

- A city provider replaces a pack provider of the same name. Pack providers are added only when
  the name is not yet defined (`internal/config/pack.go:241`, and `:450` for rig imports).
- Inheritance follows the override: with the city's `lite-t3` on pi, `lite-review` resolved
  `lite-review → lite-t3 → builtin:pi` and launched
  `pi -e .pi/extensions/gc-hooks.js --thinking xhigh --model openai/gpt-6-luna`.
- An unlisted Claude model id passes through verbatim:
  `claude --dangerously-skip-permissions --effort medium --model claude-haiku-5-5`.
- Per rig, a slot cannot be re-pointed; individual agents can, through a rig-scoped variant
  provider and a patch:

  ```toml
  [providers.st-t1]
  base = "builtin:pi"
  option_defaults = { model = "opencode-go/deepseek-v4.1-flash" }

  [[patches.agent]]
  rig = "simpletracker"
  name = "superpowers-lite.executor-t1"
  provider = "st-t1"
  ```

  `[[rigs.patches]]` works too, but takes `agent =` and the bare agent name, which is ambiguous
  when two imported packs share one; prefer `[[patches.agent]]`.

### Constraints that follow

- Every slot also becomes an on-demand implicit agent, at city scope and in every rig
  (`InjectImplicitAgents`). It costs nothing until something is slung to it. There is no switch
  to turn it off.
- Slot names use dashes. A provider named `superpowers-lite.t1` fails validation, because its
  implicit agent would carry the same name and agent names may not contain dots.
- Pack agents use only `lite-*` slots. An agent naming `claude` directly fails validation unless
  the city declares `[providers.claude]`.
- Every slot default sets `effort`. The builtin Claude default is `max`.
- Defaults use full model ids. gc's aliases lag: in 1.5.1 `opus` means `claude-opus-4-8` and
  `haiku` means `claude-haiku-4-5-20251001`.
- `[[patches.providers]]` has no `option_defaults`, so a city overrides a slot by redefining the
  whole block.
- The number of agents per slot stays small, because moving one rig to other models costs one
  patch per agent.

## Agents

| Agent | Slot | Replaces | Phase |
|---|---|---|---|
| `operator` | `lite-ops` | `gc.run-operator` (worktrees, bead lifecycle, land) | 1 |
| `card-cutter` | `lite-plan` | `gc.task-decomposer` for lite builds; converts work beads in lite-work | 1 |
| `executor-t1` | `lite-t1` | `superpowers.implementer` | 1 |
| `executor-t2` | `lite-t2` | | 1 |
| `executor-t3` | `lite-t3` | | 1 |
| `card-reviewer` | `lite-t1` | `superpowers.code-quality-reviewer` for the per-task review | 1 |
| `spec-author` | `lite-plan` | `superpowers.brainstorming` | 2 |
| `plan-author` | `lite-plan` | `superpowers.writing-plans` | 2 |
| `plan-reviewer` | `lite-plan` | `superpowers.plan-reviewer` | 2 |
| `code-reviewer` | `lite-review` | `superpowers.code-reviewer` | 2 |
| `cross-reviewer` | `lite-review-cross` | | 2 |
| `selector` | `lite-ops` | | 4 |

Prompts for these agents follow four rules:

1. **No bead lifecycle in cheap agents.** `executor-*` and `card-reviewer` read one card, change
   code or write one report file, and stop. They do not include the `gc-role-worker` fragment.
   `operator` and the check scripts close step beads and record outcomes. This is new; the
   upstream packs let every worker manage its own beads.
2. **Harness-neutral.** No Claude-only tools (Task, AskUserQuestion, slash commands), no
   "follow skill X". Whatever a step needs is in its text or in a file it is told to read.
3. **Checklists are pasted, not loaded.** The card carries its `kind` checklist (see "Task
   kinds"), so every harness and every model gets the same text and none has to decide when to
   load a skill.
4. **The drain-root guard ships with the pack**, for each supported harness: a Claude PreToolUse
   hook and a pi extension, as `gcexp/assets/pi/city-guard.js` and `guard-latch-close.py` do
   today.

## Task card

`card-cutter` writes one card per task to `<artifact_root>/cards/<task id>.md`, with front matter
validated against a `lite.card.v1` schema. Step text in gc is limited to 4096 bytes, so the card
never travels in a step description.

The card list itself rides in the decomposition artifact: `gc.build.decomposition.v1` accepts
extra front matter (tested with a `lite.cards` list), so `decompose` stays schema-valid for the
base pipeline. gascity's validator can load `lite.card.v1` from an extra schema directory named
in `GC_BUILD_SCHEMA_ROOTS` (tested: a valid card passes, a card missing a section or
`card.files` fails), but it checks only presence, not types, and check scripts receive a fixed
environment that does not carry that variable. Lite therefore ships its own `card-valid` check:
it sets `GC_BUILD_SCHEMA_ROOTS` to the pack's `schemas/build` for the base rules, then checks
types and the size cap itself (every card artifact also needs the common `producer` and `trace`
front matter the validator demands of all build artifacts).

| Section | Content |
|---|---|
| `goal` | One or two sentences. |
| `files` | The files the task may create or change. The scope check enforces it. |
| `interfaces` | Signatures and types to add or change, written out in full. |
| `context` | Excerpts of the existing code the change depends on, with paths and line ranges, so the executor does not search. |
| `steps` | The plan's steps for this task, including its code. |
| `done_when` | Commands that must pass: the task's named test, build, lint. |
| `out_of_scope` | What not to touch, and when to stop with a blocker instead of improvising. |
| `kind` | One of the task kinds below. |
| `checklist` | The kind's checklist, pasted by a script, not by the model. |

Size cap: a handful of files and about an hour of human work. The schema check rejects a card
without every section or over the cap; `plan-review` asks whether a junior developer could finish
each card without asking anything.

Because a superpowers plan already holds exact paths, code and commands, cutting is mostly
mechanical. `card-cutter` runs on `lite-plan` in phase 1 for safety; moving it to a cheaper slot
is a calibration question.

### Task kinds

`tdd-feature`, `bugfix`, `refactor`, `tests-only`, `docs`, `migration`, `ui`. Each has a
checklist file in `assets/kinds/<kind>.md`, a short list of concrete steps for that kind of
work. For `migration`: write the down migration, run both directions against a copy, compare row
counts. Phase 1 ships `bugfix` and `tdd-feature`; phase 3 adds the kinds that escalate most.

## Per-item loop

```
card ─► executor-t1 ─► checks ─┬─ pass ─► card-reviewer ─┬─ approve ─► land
                               │                        └─ reject ─┐
                               └─ fail ────────────────────────────┤
                                                                   ▼
                      reset worktree; executor-t2 gets card + failed diff + check output
                                                                   ▼
                      checks + card-reviewer ─ fail ─► human gate ─ approve ─► executor-t3
                                                                   ▼
                                       checks + card-reviewer ─ fail ─► blocked, mail human
```

- The ladder is a small state machine built from `on_complete`, so no agent spends a turn
  deciding whether a later attempt is needed, and attempts that are not needed never exist as
  beads. The item formula runs prepare, the T1 attempt and a verify step. Verify (run by
  `card-reviewer`, which first runs the checks through a pack command) writes its structured
  output as `{"next": [{"action": "land"}]}`, or `t2`, or `t3`, or `blocked`. Its `on_complete`
  bonds `superpowers-lite-next` with that action. `superpowers-lite-next` uses `condition` on
  the action to contain either the human approval gate, the attempt and another verify (which
  bonds `superpowers-lite-next` again), or only `land`. This compiles on gc 1.5.1, including the
  self-bond; see "Open questions" for what only a live run can show.
- An authored step cannot `need` the compiler's generated `<step>-fanout` control, so `land`
  cannot follow the verify step in the item formula; it lives in `superpowers-lite-next`.
- Fallback if the state machine fails at run time: a static ladder with gate steps run by
  `operator`, as compound-engineering does for its optional review lanes
  (`compound-code-review.formula.toml:93-103`). It costs one cheap agent turn per gate and
  about twice the beads (see "Open questions").
- The T3 approval (D3) is a `human` gate, one of gc's built-in gate types.
- Every attempt starts from the item's base commit (D4). The `gc.continuation_group` of v1 does
  not span attempts, since each runs on a different agent.
- The item records `lite.kind`, the tier that passed or `blocked`, and per failed attempt the
  check or review finding that failed it. Calibration and learnings read these.
- `land` and `close-source-anchor` stay as in v1, run by `operator`.

### Checks

Run as `[steps.check]` exec checks after every attempt, before any review:

| Check | Fails when |
|---|---|
| `card-done` | any `done_when` command fails |
| `diff-scope` | the diff touches a file outside `files` |
| `tests-intact` | the diff deletes a test, or adds a skip or ignore marker |
| `report-valid` | the executor's report is missing or fails its schema |
| `card-valid` | runs on `decompose`: a card is missing a section, has a wrong type or exceeds the size cap |

The scripts ship in the pack's `assets/scripts/checks/` and run from there. A check written as
`path = "../assets/scripts/checks/<name>.sh"` is rewritten at compile time to the absolute path
in the highest-priority formula layer that ships it (`internal/formula/parser.go`,
`resolveCheckPaths`), and the dispatcher trusts paths beside any formula layer
(`internal/dispatch/ralph.go`, `ralphCheckTrustedAbsoluteRoots`). Verified in the scratch city: a
pack formula's check compiled to `<pack>/assets/scripts/checks/scope-ok.sh`. Nothing is copied into
rigs, and scripts find their siblings through their own directory.

The gascity pack has shipped its checks the same way since before `390cac1a`, but its formulas at
that pin still name `.gc/scripts/checks/...`; gascity-packs main has moved 29 check paths to the
`../assets/` form, while superpowers on main still uses `.gc/scripts`. Lite's own steps use the
`../assets/` form throughout, including where they reuse gascity's `build-artifact-valid.sh`,
which then runs beside its own validator and schemas. That removes the gcexp CLAUDE.md
workaround ("give the validator its schemas") for every step lite owns.

### Scripts agents run

Steps that need a script but are not checks (land, commit-docs, pasting the kind checklist into
a card, recording an escalation) call pack commands instead of inlining shell in step text. A
directory `commands/<name>/run.sh` becomes `gc <binding> <name>`, and gc runs it with
`GC_PACK_DIR` set to the pack, so it reaches anything under `assets/`. The gascity pack's own
claim step works this way (`gc gc claim`). Verified in the scratch city: `gc tp hello one two`
ran the pack's script with `GC_PACK_DIR` and the arguments, and the script called a sibling in
`assets/scripts/`.

Two conditions, both documented in the README:

- Lite is imported at city scope. A rig-only import does not expose its commands, from the city
  directory or from the rig.
- The binding is named `superpowers-lite`. Step text names the command as
  `gc superpowers-lite <name>`, as gascity's prompts assume the binding `gc`.

This also retires v1's inlined land and commit-docs blocks, and the 4096-byte step text limit
stops constraining them.

## Calibration and metrics

A `superpowers-lite-calibrate` formula runs a fixed set of 10 to 20 cards with known outcomes
against the current slot bindings. It records per card: check pass rate, escalations, review
findings, wall time and tokens. Rerun it when a model ships or a subscription changes; it answers
questions such as whether gpt-6-luna is strong enough for `lite-t3`. Until then, gpt-6-luna stays
in `lite-review-cross`, where simpletracker already uses it.

The first cards come from simpletracker's history, then from the other rigs. The pack declares
`[[pricing]]` entries for its default models; cities add their own.

gc records model token usage only for the `claude` and `codex` harness families
(`internal/worker/invocation_telemetry.go`, `invocationUsageSpecs`); pi, opencode and the rest
are skipped. gcexp's `.gc/usage.jsonl` holds 4849 compute facts and no model facts at all, not
even for Claude sessions, for a reason not yet traced. Calibration therefore reads token counts
from each session's own transcript, and for gateway-billed models (opencode-go, OpenRouter)
cross-checks against the gateway's usage report.

The per-item records also give an escalation rate per kind: a kind that never escalates can
start on a cheaper slot, and one that escalates often can start at T2.

## Learnings and panels (phase 4)

- A periodic T2 step reads failed attempts and proposes checklist lines for the kinds that fail,
  as compound-engineering's compound step does. A human merges them.
- Optional discovery panel before requirements, using the fork's discovery roles as a lane list
  (product, users, domain, existing solutions, dependencies): `selector` picks lanes, T2
  researches, `lite-plan` merges, a human approves.
- Optional design-review panel for UI work: UX, information architecture, UI, accessibility.

## Relation to superpowers

v2 keeps six of nine stages as superpowers runs them. It overrides `decompose` and the whole
per-item formula by step id, and replaces every agent. Lite's existing rule applies: bump the
superpowers pin and lite together, and recompile every lite formula after a bump.

If superpowers bumps keep breaking the overrides, lite drops the superpowers import, extends
gascity's `build-base` directly and vendors the brainstorming and planning prompts it still
uses. superpowers is MIT-licensed.

## Upstream drafts (D5)

For the owner to review and file, kept in `gcexp/upstream-drafts/`:

1. Install hooks for an agent's resolved harness. Today `install_agent_hooks` is per agent and
   does not follow the provider (`internal/config/resolve.go:143`), so moving a slot to pi leaves
   agents without `.pi/extensions/gc-hooks.js`, which pi's builtin args load.
2. A rig-level provider alias, for example `[rigs.provider_aliases] lite-t1 = "st-t1"`, so one rig
   can re-point a slot with one line instead of one patch per agent.

## Phases

| Phase | Scope | Done when |
|---|---|---|
| 1 | Slots; `operator`, `card-cutter`, executors, `card-reviewer`; card schema; checks; per-item loop; `bugfix` and `tdd-feature` kinds; lite-work on the loop; first calibration cards | lite-work drains a simpletracker convoy with T1 on a cheap model, and every escalation is recorded |
| 2 | lite-build: own planning and review agents, `decompose` emits cards, cross-family review | a lite-build run completes with only `lite-*` agents |
| 3 | More kinds, chosen by escalation rate; calibration formula | each kind has an escalation rate from real runs |
| 4 | Learnings step; discovery and design panels | |

## Open questions

Answered on 2026-11-06 in a scratch city (gc 1.5.1, superpowers and gascity at `390cac1a`),
by compiling formulas with `gc formula show` and reading gc's source. No controller ran.

| # | Question | Answer |
|---|---|---|
| 1 | Can a gate be a script instead of an agent? | No. Gate types are `gh:run`, `gh:pr`, `timer`, `human` and `mail`; `condition` is decided at compile time. Escalation uses the `on_complete` state machine instead (see "Per-item loop"), which needs no gate. |
| 2 | Can a card schema sit next to `gc.build.decomposition.v1`? | Yes; see "Task card". |
| 3 | Beads per item | v1 `superpowers-lite-work-item`: 21. Static ladder with gates: 20. State machine: 9 when T1 passes (6 + 3 for land), 14 with a T2 escalation, 7 more for T3. |
| 4 | Token usage for pi? | No; see "Calibration and metrics". |
| 5 | Dots in provider names? | No; slots use dashes. |
| 6 | Does `../assets/scripts/checks/build-artifact-valid.sh` reach gascity's copy through superpowers? | Yes. It compiled to `gascity/assets/scripts/checks/build-artifact-valid.sh` of the `390cac1a` snapshot. |

Still open, needing a live run in a throwaway city with its own supervisor:

1. Whether a `fanout` control waits for its bonded molecules before closing, so the item's
   `workflow-finalize` covers the whole escalation chain.
2. Whether bonded molecules inside a drain item inherit the item's work directory and source
   anchor, so a T2 attempt and `land` act on the right worktree and bead.
3. How the verify step writes `gc.output_json`: through a pack command the reviewer runs, so
   the JSON never depends on the model formatting it.
4. Why gcexp records no model usage facts even for Claude.

Risks:

- The superpowers pin grows heavier with every override (see "Relation to superpowers").
- Model choices stay opinion until the calibration cards exist, so phase 1 writes them.

## References

- `danbak0757/opencode`, commits `9a56d46` to `be580e0` (2026-10-28 to 10-30): 67 agents,
  `COORDINATION.md`, `team_run`, work modes.
- `gastownhall/gascity-packs` at `796d7ec`: `compound-engineering` (selector and gate lanes),
  `superpowers`, `bmad`, `gstack`, `gascity` (`build-base`, decomposition schema).
- gc v1.5.1 (`4f698fe`): `docs/guides/configuring-an-agent.md`, `docs/reference/specs/pack-spec.md`
  §1.2.7, `internal/config/pack.go`, `internal/config/resolve.go`,
  `internal/worker/builtin/profiles.go`.
- Aider polyglot leaderboard, architect mode entries.
