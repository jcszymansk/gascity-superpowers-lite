# superpowers-lite v2: tiered delegation

Status: phase 1 closed 2026-11-07, phase 2 not started. Proposed 2026-11-06 against superpowers-lite
at `23a64c6`, superpowers at `390cac1a`, gc 1.5.1.

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
  output (`superpowers/skills/writing-plans/SKILL.md:10,117-119`). Cards deliberately leave that
  code out; see "Task card".
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

1. **No bead lifecycle in any agent.** Every agent claims, finishes and closes its step through
   pack commands (see "Scripts agents run") and never runs `bd` or `git commit`, or types a bead
   id. They share the `lite-step-worker` fragment instead of `gc-role-worker`. This is new; the
   upstream packs let every worker manage its own beads.
2. **Harness-neutral.** No Claude-only tools (Task, AskUserQuestion, slash commands), no
   "follow skill X". Whatever a step needs is in its text or in a file it is told to read.
3. **Checklists are pasted, not loaded.** The card carries its `kind` checklist (see "Task
   kinds"), so every harness and every model gets the same text and none has to decide when to
   load a skill.
4. **The drain-root guard ships with the pack**, for each supported harness: a Claude PreToolUse
   hook and a pi extension, as `gcexp/assets/pi/city-guard.js` and `guard-latch-close.py` do
   today. Deferred from phase 1: `claim` already releases a drain root itself, and agents
   that never run `bd` have nothing to guard.

## Task card

`card-cutter` writes one card per task to `<artifact_root>/cards/<task id>.md`, with front matter
validated against a `lite.card.v1` schema. Step text in gc is limited to 4096 bytes, so the card
never travels in a step description.

Phase 1 cards use TOML front matter between `+++` lines (`schema = "lite.card.v1"`, `id`,
`kind`, `files`, `done_when`) and Markdown sections, validated by lite's own parser
(`assets/litetools/card.py`), which reports every problem at once. Lite does not use gascity's
build-artifact validator for cards: it checks presence only, not types, and needs PyYAML and a
schema root passed through the environment. For phase 2, the card list can ride in the
decomposition artifact, since `gc.build.decomposition.v1` accepts extra front matter (tested with
a `lite.cards` list).

| Section | Content |
|---|---|
| `goal` | One or two sentences. |
| `files` | The files the task may create or change. The scope check enforces it. |
| `interfaces` | Signatures and types to add or change, without bodies. At most 40 lines of code. |
| `context` | Excerpts of the existing code the change depends on, with paths and line ranges, so the executor does not search. Every line of a code block must exist in the repository. |
| `steps` | What to change and why, and each test by name with the behaviour it pins down. No code. |
| `done_when` | Commands that must pass: the task's named test, build, lint. |
| `out_of_scope` | What not to touch, and when to stop with a blocker instead of improvising. |
| `kind` | One of the task kinds below. |
| `checklist` | The kind's checklist, pasted by a script, not by the model. |

Size cap: a handful of files and about an hour of human work. The schema check rejects a card
without every section or over the cap; `plan-review` asks whether a junior developer could finish
each card without asking anything.

Cards hold no implementation or test code. In the first real run (simpletracker, 2026-11-07) the
cards carried it: 305 of 311 and 378 of 386 added lines were verbatim in the card, and `card-cutter`
on Opus wrote 82,264 output tokens against 37,926 for `executor-t1`. Haiku passed both items without
having solved anything, and no escalation could happen. `cut-card-finish` now refuses code blocks
outside `interfaces` and `context`, code-style indented lines, long inline code and context
lines that are not in the repository. An 8 KiB limit on the rest of the card was dropped on
2026-11-08: it caused most refusals, and prose pseudocode passed it anyway. Verify records
`lite.card_overlap.<tier>` instead, the share of the attempt's added lines found verbatim in
the card, which shows copied code however the card wrote it. `card-cutter` runs on `lite-plan`
in phase 1 for safety; moving it to a cheaper slot is a calibration question.

This conflicts with phase 2's mechanical cutting: a superpowers plan holds complete code in every
step, and pasting it into a card would bring the same problem back. Phase 2 has to choose between
plans without code and cards that leave it out.

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
                      executor-t1 retry, from the rejected attempt + its findings
                      (skipped when the executor reported a blocker)
                                                                   ▼
                      checks + card-reviewer ─ fail ───────────────┤
                                                                   ▼
                      reset worktree; executor-t2 gets card + failed diff + check output
                                                                   ▼
                      checks + card-reviewer ─ fail ─► human gate ─ approve ─► executor-t3
                                                                   ▼
                                       checks + card-reviewer ─ fail ─► blocked, mail human
```

- The ladder is a small state machine built from `on_complete`, so no agent spends a turn
  deciding whether a later attempt is needed, and attempts that are not needed never exist as
  beads. The item formula runs prepare, cut-card, the T1 attempt and a verify step. Verify (run by
  `card-reviewer`, which first runs the checks through a pack command) writes its structured
  output as `{"next": [{"action": "land", "round": "1"}]}`, or `t1` with round 2 for the T1
  retry, or `t2`, or `t3`, or `blocked`. Its `on_complete` bonds `superpowers-lite-next` with
  that action and round. `superpowers-lite-next` uses `condition` on
  the action to contain either the human approval gate, the attempt and another verify (which
  bonds `superpowers-lite-next` again), or only `land`. A live run on gc 1.5.1 confirmed it
  end to end (see "Open questions").
- `superpowers-lite-next` must be `type = "expansion"` with `[[template]]` steps; `fanout`
  refuses a workflow formula. Its fragments join the item workflow (`gc.root_bead_id` is the
  item root, `gc.dynamic_fragment=true`), and the item's `workflow-finalize` waits for the
  whole chain.
- Template fields use single braces (`gc.run_target = "superpowers-lite.executor-{action}"`);
  `condition` keeps double braces (`{{action}} == t3`). Item vars such as `issue` do not reach
  the fragments on their own, so the bond passes them: `vars = { action = "{item.action}",
  issue = "{{issue}}" }` in the item formula and `issue = "{issue}"` in the self-bond.
- An authored step cannot `need` the compiler's generated `<step>-fanout` control, so `land`
  cannot follow the verify step in the item formula; it lives in `superpowers-lite-next`.
- `blocked` is a verify step that closes with `gc.outcome=fail` and `next: []`: no fragment is
  bonded, and the item and its drain fail.
- Fallback if the state machine had failed at run time: a static ladder with gate steps run by
  `operator`, as compound-engineering does for its optional review lanes
  (`compound-code-review.formula.toml:93-103`). It costs one cheap agent turn per gate and
  about twice the beads (see "Open questions").
- The T3 approval (D3) is a `human` gate, one of gc's built-in gate types. The approval step
  needs `gc.run_target` set to `operator`; without one it stays open with no owner.
- Every attempt starts from the item's base commit (D4). The `gc.continuation_group` of v1 does
  not span attempts, since each runs on a different agent.
- The item records `lite.kind`, the tier that passed or `blocked`, and per failed attempt the
  check or review finding that failed it. Calibration and learnings read these.
- `land` and `close-anchor` are pack commands run by `operator`. `land` is v1's compare-and-swap
  block ported to Python; it no longer reads a task review, since it requires the
  `lite.passed_tier` that only an approving verdict sets.

### Checks

The `verify` command runs every check in the reviewer's session, before the review:

| Check | Fails when |
|---|---|
| `report-valid` | the executor's report is missing or malformed |
| `executor` | the executor reported a blocker instead of a change |
| `worktree-clean` | the attempt left uncommitted changes |
| `diff-scope` | the diff is empty, or touches a file outside `files` |
| `no-skip-markers` | the diff adds a skip or ignore marker |
| `card-done` | any `done_when` command fails |

`done_when` runs in a detached runner (`litetools/donewhen.py`), double-forked into its own
session, with its state under `<attempt dir>/checks/`: what it checks (commit and commands), its
pid, its log and, when done, its result. One `verify` waits for it at most 100 seconds
(`LITE_VERIFY_WAIT_SECONDS`), under the two minutes an agent's shell tool waits by default, and
then reports that the checks still run without closing the step. A longer wait relied on the
agent passing a longer tool timeout; Haiku did not, the tool moved verify to the background, and
the session was drained while it waited for it. The next `verify`, from the same
session or a restarted one, attaches to the same run; a runner that died without a result is
started again. The quick checks run once per attempt commit and are saved beside it, because
once `done_when` starts, its build products would fail `worktree-clean` on a second `verify`.
This exists because gc 1.5.1 drains a pool session that holds a claimed step while idle at its
prompt for 90 seconds (its execution backstop), and that drain killed a reviewer waiting on a
backgrounded `verify`: fnr-lka81.1's review restarted nine times in 45 minutes and never finished.

Removed tests are not a check. A fix that deletes code also deletes that code's tests, so
`verify` lists deleted test files and test declarations removed on net, and the reviewer accepts
a removal only when the card asks for it or the diff deletes or replaces the code the test
exercised. Until 2026-11-10 a removal failed a `tests-intact` check, which no card could
override, so a bead that removed `MainScreenModel.artworkChanged` and its test could not pass
at any tier (FreeNetRadio fnr-5pfxs).

Card validity is checked when the card is cut: `cut-card-finish` refuses an invalid card and the
step stays open until the cutter fixes it. After the checks, `verify` resets the worktree to the
attempt commit, because `done_when` commands leave build products behind (a Python test run
leaves `__pycache__/`) that `land` would refuse as a dirty worktree. Ignored files survive.

The checks are not `[steps.check]` scripts, as first planned. A check script runs only after the
agent has closed its bead, in the controller's environment with a fixed `PATH` and none of the
project's toolchain, so `done_when` commands such as `nix develop --command ./gradlew test` could
not run there. (A pack formula's `path = "../assets/scripts/checks/<name>.sh"` does compile to the
pack's absolute path and is trusted by the dispatcher, should a later check suit that model.)

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

This also retires v1's inlined land block, and the 4096-byte step text limit stops constraining
it. Phase 1 commands: `claim`, `prepare-worktree`, `cut-card-start`, `cut-card-finish`,
`attempt-start`, `attempt-finish`, `verify`, `verdict`, `approval`, `approve`, `land` and
`close-anchor`. `claim` wraps `gc hook --claim --drain-ack --json` and remembers the claimed step
in a file keyed by session, so later commands need no bead id. Every `bd` call passes
`--rig $GC_RIG`, because a worktree outside the rig would make gc pick the wrong store.

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
are skipped. gc finds Claude transcripts only under `~/.claude/projects`
(`sessionlog.DefaultSearchPaths`) plus `[daemon] observe_paths`, and ignores
`CLAUDE_CONFIG_DIR`. A city whose agents run with `CLAUDE_CONFIG_DIR` set records no model facts
until `observe_paths` names `$CLAUDE_CONFIG_DIR/projects`. That is why gcexp's
`.gc/usage.jsonl` holds 4849 compute facts and no model facts at all. Calibration reads
`kind = "model"` facts for Claude and Codex once that is fixed, reads the session's transcript
for other harnesses, and for gateway-billed models (opencode-go, OpenRouter) cross-checks
against the gateway's usage report.

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
   does not follow the provider (`internal/config/resolve.go:144`), so moving a slot to pi leaves
   agents without `.pi/extensions/gc-hooks.js`, which pi's builtin args load. Upstream already
   tracks this as gascity#4375, with an unmerged fix in #4376, so the draft is a comment there:
   `gascity-4375-comment-hooks-follow-provider.md`.
2. Rig-level providers, `[rigs.providers.<name>]` shadowing the city's (or the lighter alias
   form, `[rigs.provider_aliases] lite-t1 = "st-t1"`), so one rig can re-point a slot with one
   block instead of one patch per agent: `gascity-rig-provider-overrides.md`.

## Phases

| Phase | Scope | Done when |
|---|---|---|
| 1 | Slots; `operator`, `card-cutter`, executors, `card-reviewer`; card schema; checks; per-item loop; `bugfix` and `tdd-feature` kinds; lite-work on the loop; first calibration cards | lite-work drains a simpletracker convoy with T1 on a cheap model, and every escalation is recorded |
| 2 | lite-build: own planning and review agents, `decompose` emits cards, cross-family review | a lite-build run completes with only `lite-*` agents |
| 3 | More kinds, chosen by escalation rate; calibration formula | each kind has an escalation rate from real runs |
| 4 | Learnings step; discovery and design panels | |

Phase 1 closed on 2026-11-07. A simpletracker convoy drained with T1 on Haiku, and the one real
escalation (`smt-rl47`, T1 to T2) was recorded on the work bead and in its findings. The T3 gate and
attempt ran only in the lab: forcing a real one needs a bead that both Haiku and Sonnet fail, and
none has turned up. The first real T3 still stops at the gate for a human `approve`.

## Open questions

Answered on 2026-11-06 in a scratch city (gc 1.5.1, superpowers and gascity at `390cac1a`),
by compiling formulas with `gc formula show` and reading gc's source. No controller ran.

| # | Question | Answer |
|---|---|---|
| 1 | Can a gate be a script instead of an agent? | No. Gate types are `gh:run`, `gh:pr`, `timer`, `human` and `mail`; `condition` is decided at compile time. Escalation uses the `on_complete` state machine instead (see "Per-item loop"), which needs no gate. |
| 2 | Can a card schema sit next to `gc.build.decomposition.v1`? | Yes; see "Task card". |
| 3 | Beads per item | v1 `superpowers-lite-work-item`: 21. Static ladder with gates: 20. State machine, compiled: 9 when T1 passes, 14 with a T2 escalation, 7 more for T3. Measured in the live run: 7, 10, and about 5 more for T3. |
| 4 | Token usage for pi? | No; see "Calibration and metrics". |
| 5 | Dots in provider names? | No; slots use dashes. |
| 6 | Does `../assets/scripts/checks/build-artifact-valid.sh` reach gascity's copy through superpowers? | Yes. It compiled to `gascity/assets/scripts/checks/build-artifact-valid.sh` of the `390cac1a` snapshot. |

Answered the same day by a live run in a throwaway city (`GC_HOME` plus `GC_ISOLATED=1`, its
own supervisor and control dispatcher). Agents were suspended and their steps were closed by
hand with `gc bd update` and `gc bd close`, so no model ran:

| # | Question | Answer |
|---|---|---|
| 7 | Does a `fanout` wait for its bonded molecules, so `workflow-finalize` covers the chain? | Yes. The item root closed only after the last fragment (land, or a failed verify). |
| 8 | Do bonded fragments act on the item's worktree and source anchor? | Fragments carry the item's root, so steps find the source anchor through `gc.root_bead_id` and read `work_dir` from it as v1 does. Vars like `issue` must be passed through the bond (see "Per-item loop"). |
| 9 | How does verify write `gc.output_json`? | `gc bd update <step> --set-metadata gc.output_json=...` before closing, which a pack command can run so the JSON never depends on the model formatting it. The command itself is not tested yet. |

Answered by the phase 1 lab run (2026-11-06, same throwaway city setup). The pack was imported
at city scope from the working copy, its agents ran `sleep` instead of a model, and each step was
played by running the real pack commands inside a live session's environment, through the real
`gc hook --claim`. Two items ran: one rejected at T1 (diff scope) and T2 (review), approved by a
human and passed at T3; one approved at T1, landed and closed.

| # | Question | Answer |
|---|---|---|
| 11 | Do pack commands get their arguments? | Yes, verbatim, including quoted multi-word values; gc imposes no timeout. |
| 12 | Are scope=rig agents of a city-scope import created in each rig? | Yes. Rigs need no import of their own. |
| 13 | What does the T3 gate look like? | A bead of type `gate` with `gc.root_bead_id` set to the item root, which `needs` it. It inherits the bonding step's route (`card-reviewer`), but `bd ready` leaves gates out, so no agent can claim it, and it starts no session. `approve` closes it. |
| 14 | Beads per item, measured | 8 under the item root when T1 passes, 16 for T1, T2 and T3. |
| 15 | Does a step run when the step it needs failed? | Yes: `close-anchor` ran after a refused `land`. It checks the landed commit itself and fails safely. |
| 16 | Can a lab process pose as a session? | Only with a live session's identity: the controller SIGTERMs processes whose `GC_SESSION_ID` names no session it knows (`cmd/gc/session_beads.go`), and `gc hook` without one reports `drain`. |

Traced from gc's source and checked against gcexp's session beads:

| # | Question | Answer |
|---|---|---|
| 10 | Why does gcexp record no model usage facts even for Claude? | gc searches `~/.claude/projects` for transcripts, but gcexp's agents run with `CLAUDE_CONFIG_DIR=~/.config/claude-priv`. `gc session logs mayor` fails the same way and succeeds once the real `projects` directory is on the search path. See "Calibration and metrics". |

Risks:

- The superpowers pin grows heavier with every override (see "Relation to superpowers").
- Model choices stay opinion until the calibration cards exist, so phase 1 writes them.
- Real runs cover T1 and T2 only (simpletracker, 2026-11-07). Three no-code items ran: two passed at
  T1, and `smt-rl47` was rejected at T1 for missing docstrings and passed at T2. The T3 gate and a
  T3 attempt have run only in the lab, with the agents played by hand.
- Cards still carry the design. `smt-rl47`'s Steps spell out the lexer as prose (frame stack,
  dollar-run rule, parse order), and `card-cutter` wrote 105,104 output tokens on Opus for that one
  card against 74,475 for `executor-t1`. So these runs show that Haiku can implement a written
  design, and the cutter stays the main expense.
- Replays on a rig leak. Cutters inspect git history and the disk unprompted: `smt-rl47`'s Opus cutter
  read the historical solution in `simpletracker-impl`, and `smt-ura1`'s Sonnet cutter found
  `smt-rl47`'s card and landed code and copied the card (11 diff lines of 218). Neither run measures
  how well that model designs, so calibration needs a repository and artifact tree holding only
  the base snapshot. Executors and reviewers read nothing outside their own item in those runs.
- One clean comparison so far (2026-11-07, a rig holding only the base snapshot, one run each):
  Opus cut that card with 40,989 output tokens and 1 refusal in about 6 minutes, Sonnet 5 with
  67,854 tokens and 9 refusals in about 13 minutes. Both cards led Haiku to a T1 pass on all 36
  independent tests. At list prices Sonnet came out dearer, because its longer session re-read
  more cache, so `lite-plan` stays on Opus. The 8 KiB cap caused most of the refusals and was dropped.
- T1 gets one retry before T2 (added 2026-11-08). The only real escalation so far
  (`smt-rl47`) went to Sonnet to add docstrings, which Haiku could have fixed. The retry path is
  covered by unit tests; no real run has taken it yet.
- The per-item reviewer caught a real behavioural gap in a harness trial (2026-11-07): given the
  historical solution, which fails 5 of the 36 independent tests, Haiku rejected 6 of 6 and named
  the header and string-template faults each time, and it approved a good diff 3 of 3. That diff
  was far from its card, though, so a subtle bug in a diff that follows the card is still untested.

## References

- `danbak0757/opencode`, commits `9a56d46` to `be580e0` (2026-10-28 to 10-30): 67 agents,
  `COORDINATION.md`, `team_run`, work modes.
- `gastownhall/gascity-packs` at `796d7ec`: `compound-engineering` (selector and gate lanes),
  `superpowers`, `bmad`, `gstack`, `gascity` (`build-base`, decomposition schema).
- gc v1.5.1 (`4f698fe`): `docs/guides/configuring-an-agent.md`, `docs/reference/specs/pack-spec.md`
  §1.2.7, `internal/config/pack.go`, `internal/config/resolve.go`,
  `internal/worker/builtin/profiles.go`.
- Aider polyglot leaderboard, architect mode entries.
