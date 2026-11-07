"""The pack commands, one function per ``gc superpowers-lite <name>``.

Agents never manage beads themselves. Each command checks that the claimed
step is the kind it expects (``lite.step``), does its deterministic work, and
closes only that step. Per-item state lives on the source anchor.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from litetools import card as cards
from litetools import checks, gitops
from litetools import report as reports
from litetools.context import (
    Env,
    Item,
    Layout,
    claimed_bead_id,
    forget_claim,
    layout_for,
    resolve_item,
    save_claim,
    step_tier,
)
from litetools.gc import Bead, Gc
from litetools.ladder import Action, Decision, Tier, Verdict, decide
from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

DONE_WHEN_TIMEOUT_SECONDS = 15 * 60
OPEN_STATUSES = ("open", "in_progress")


@dataclass(frozen=True, slots=True)
class Ctx:
    """What every command runs with.

    Attributes:
        env: The agent environment.
        gc: The gc CLI.
    """

    env: Env
    gc: Gc


@dataclass(frozen=True, slots=True)
class Done:
    """A command's successful result.

    Attributes:
        message: Printed to stdout for the agent.
        drain: True when the command closed the session's step, so the CLI
            acknowledges the drain after printing.
    """

    message: str
    drain: bool = False


Outcome = Result[Done, str]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: Path, text: str) -> Result[None, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        return Err(f"could not write {path}: {error}")
    return Ok(None)


def _read(path: Path) -> Result[str, str]:
    try:
        return Ok(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Err(f"could not read {path}: {error}")


def _claimed_step(ctx: Ctx, expected: str) -> Result[Item, str]:
    bead_id = claimed_bead_id(ctx.env)
    if isinstance(bead_id, Err):
        return bead_id
    step = ctx.gc.show(bead_id.value)
    if isinstance(step, Err):
        return step
    bead = step.value
    if bead.status not in OPEN_STATUSES:
        return Err(f"claimed step {bead.bead_id} is {bead.status}; claim again")
    if bead.assignee and bead.assignee not in ctx.env.identities:
        return Err(f"claimed step {bead.bead_id} is assigned to {bead.assignee}, not to this session")
    if bead.meta("lite.step") != expected:
        return Err(
            f"claimed step {bead.bead_id} is a '{bead.meta('lite.step') or 'non-lite'}' step; "
            f"this command handles '{expected}' steps"
        )
    return resolve_item(ctx.gc, bead)


def _close_step(
    ctx: Ctx, step: Bead, outcome: str, reason: str, extra: dict[str, str] | None = None
) -> Result[None, str]:
    values = {"gc.outcome": outcome, **(extra or {})}
    updated = ctx.gc.set_metadata(step.bead_id, values)
    if isinstance(updated, Err):
        return updated
    closed = ctx.gc.close(step.bead_id, reason)
    if isinstance(closed, Err):
        return closed
    after = ctx.gc.show(step.bead_id)
    if isinstance(after, Err):
        return after
    if after.value.status != "closed":
        return Err(f"step {step.bead_id} is still {after.value.status} after closing")
    forget_claim(ctx.env)
    log.info("closed step %s with gc.outcome=%s: %s", step.bead_id, outcome, reason)
    return Ok(None)


def _layout(ctx: Ctx, item: Item) -> Layout:
    return layout_for(ctx.env, item.anchor.bead_id)


def _workdir(item: Item) -> Result[Path, str]:
    raw = item.anchor.meta("work_dir")
    if not raw:
        return Err(f"source anchor {item.anchor.bead_id} has no work_dir; prepare-worktree did not run")
    path = Path(raw)
    return Ok(path) if path.is_dir() else Err(f"worktree {path} does not exist")


def _sealed_card(ctx: Ctx, item: Item) -> Result[cards.Card, str]:
    text = _read(_layout(ctx, item).card)
    if isinstance(text, Err):
        return text
    parsed = cards.parse(text.value, require_checklist=True)
    if isinstance(parsed, Err):
        return Err("the sealed card is invalid: " + "; ".join(parsed.error))
    if parsed.value.card_id != item.anchor.bead_id:
        return Err(f"the card is for {parsed.value.card_id}, not {item.anchor.bead_id}")
    return parsed


# --- claim -------------------------------------------------------------------


def _release_drain_root(ctx: Ctx, bead: Bead) -> Result[None, str]:
    out = ctx.gc.bd(
        "update", bead.bead_id, f"--if-assignee={bead.assignee}", "--assignee=",
        "--unset-metadata=gc.claimed_at", "--unset-metadata=gc.session_id", "--unset-metadata=gc.session_name",
    )
    return out if isinstance(out, Err) else Ok(None)


def claim(ctx: Ctx) -> Outcome:
    """Claim one routed step and print what to do with it."""
    data = ctx.gc.claim()
    if isinstance(data, Err):
        return data
    action = data.value.get("action")
    if action == "drain":
        forget_claim(ctx.env)
        return Ok(Done("No work: you are drained. Exit now."))
    bead_id = data.value.get("bead_id")
    if action != "work" or not isinstance(bead_id, str) or not bead_id:
        return Err(f"gc hook --claim returned no work: {json.dumps(data.value)[:300]}")
    bead = ctx.gc.show(bead_id)
    if isinstance(bead, Err):
        return bead
    step = bead.value
    if step.meta("gc.kind") == "workflow" and not step.meta("gc.root_bead_id"):
        released = _release_drain_root(ctx, step)
        detail = "released it" if isinstance(released, Ok) else f"could not release it: {released.error}"
        return Ok(Done(f"Claimed {bead_id}, a drain item root, which is not work; {detail}. Exit now.", drain=True))
    if step.status not in OPEN_STATUSES or (step.assignee and step.assignee not in ctx.env.identities):
        return Err(f"claim verification failed for {bead_id}: status {step.status}, assignee {step.assignee}")
    routed = step.meta("gc.routed_to")
    if ctx.env.route and routed and routed != ctx.env.route:
        return Err(f"claim verification failed for {bead_id}: routed to {routed}, not {ctx.env.route}")
    saved = save_claim(ctx.env, bead_id)
    if isinstance(saved, Err):
        return saved
    return Ok(Done(f"Claimed step {bead_id}: {step.title}\n\n{step.description.strip()}\n"))


# --- prepare-worktree --------------------------------------------------------


def _default_branch(ctx: Ctx) -> Result[str, str]:
    rig = ctx.env.rig_root
    if gitops.git_ok(rig, "remote", "get-url", "origin"):
        head = gitops.git(rig, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if isinstance(head, Err):
            gitops.git(rig, "remote", "set-head", "origin", "--auto")
            head = gitops.git(rig, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if isinstance(head, Err):
            return Err("origin has no HEAD; run `git remote set-head origin --auto` in the rig")
        branch = head.value.strip().removeprefix("origin/")
        fetched = gitops.git(rig, "fetch", "--prune", "origin", branch)
        if isinstance(fetched, Err):
            return Err(f"fetching origin/{branch} failed: {fetched.error}")
        return Ok(branch)
    listing = ctx.gc.run("--city", str(ctx.env.city), "rig", "list", "--json")
    if isinstance(listing, Err):
        return listing
    try:
        rigs = json.loads(listing.value).get("rigs", [])
    except (json.JSONDecodeError, AttributeError):
        return Err("gc rig list printed unexpected JSON")
    branch = next((r.get("default_branch", "") for r in rigs if r.get("name") == ctx.env.rig), "")
    if not branch:
        return Err(f"rig {ctx.env.rig} has no origin remote and no default_branch")
    return Ok(str(branch))


def prepare_worktree(ctx: Ctx) -> Outcome:
    """Create the item's worktree on its target branch and record it on the anchor.

    Any failure closes the step as failed, so the item fails instead of stalling.
    """
    found = _claimed_step(ctx, "prepare-worktree")
    if isinstance(found, Err):
        return found
    prepared = _prepare(ctx, found.value)
    if isinstance(prepared, Err):
        return _fail(ctx, found.value.step, prepared.error)
    closed = _close_step(ctx, found.value.step, "pass", prepared.value)
    return closed if isinstance(closed, Err) else Ok(Done(f"Prepared: {prepared.value}.", drain=True))


def _prepare(ctx: Ctx, item: Item) -> Result[str, str]:
    rig = ctx.env.rig_root
    anchor = item.anchor
    default = _default_branch(ctx)
    if isinstance(default, Err):
        return default
    target = anchor.meta("target")
    if not target and item.parent_convoy_id:
        parent = ctx.gc.show(item.parent_convoy_id)
        if isinstance(parent, Err):
            return parent
        target = parent.value.meta("target")
    target = target or f"lite/{anchor.bead_id}"
    if target == default.value:
        return Err(f"target {target} is the default branch; only a human merges into it")
    has_remote = gitops.git_ok(rig, "remote", "get-url", "origin")
    base_ref = (
        f"refs/heads/{target}"
        if gitops.git_ok(rig, "rev-parse", "--verify", "-q", f"refs/heads/{target}")
        else (f"origin/{default.value}" if has_remote else f"refs/heads/{default.value}")
    )
    base = gitops.rev(rig, base_ref)
    if isinstance(base, Err):
        return base
    worktree = ctx.env.city / ".gc" / "worktrees" / ctx.env.rig / anchor.bead_id
    recorded = anchor.meta("lite.base_commit")
    if worktree.exists():
        common = gitops.git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
        rig_common = gitops.git(rig, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if isinstance(common, Err) or isinstance(rig_common, Err) or common.value != rig_common.value:
            return Err(f"{worktree} exists and is not a worktree of {rig}")
        if not recorded or not gitops.is_ancestor(worktree, recorded, "HEAD"):
            return Err(f"{worktree} exists but does not descend from a recorded base commit")
        base_commit = recorded
        log.info("reusing worktree %s at base %s", worktree, base_commit)
    else:
        worktree.parent.mkdir(parents=True, exist_ok=True)
        added = gitops.git(rig, "worktree", "add", str(worktree), "--detach", base.value)
        if isinstance(added, Err):
            return added
        base_commit = base.value
    log.info("item %s: target %s, base %s (%s)", anchor.bead_id, target, base_ref, base_commit)
    layout = _layout(ctx, item)
    recorded_meta = {
        "work_dir": str(worktree),
        "target": target,
        "lite.base_commit": base_commit,
        "lite.artifact_dir": str(layout.root),
    }
    for bead_id, values in ((anchor.bead_id, recorded_meta), (item.root.bead_id, {"lite.anchor_id": anchor.bead_id})):
        updated = ctx.gc.set_metadata(bead_id, values)
        if isinstance(updated, Err):
            return updated
    check = ctx.gc.show(anchor.bead_id)
    if isinstance(check, Err):
        return check
    if any(check.value.meta(k) != v for k, v in recorded_meta.items()):
        return Err(f"metadata on {anchor.bead_id} did not read back as written")
    layout.root.mkdir(parents=True, exist_ok=True)
    return Ok(f"worktree {worktree} on {target} at {base_commit}")


# --- cut-card ----------------------------------------------------------------


def cut_card_start(ctx: Ctx) -> Outcome:
    """Print the work bead and where to write its card."""
    found = _claimed_step(ctx, "cut-card")
    if isinstance(found, Err):
        return found
    item = found.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    template = _read(ctx.env.pack_dir / "assets" / "templates" / "card.md")
    if isinstance(template, Err):
        return template
    layout = _layout(ctx, item)
    kinds = ", ".join(kind.value for kind in cards.Kind)
    return Ok(
        Done(
            "\n".join(
                [
                    f"Work bead {item.anchor.bead_id}: {item.anchor.title}",
                    "",
                    item.anchor.description.strip() or "(no description)",
                    "",
                    f"Repository worktree (read it, change nothing): {workdir.value}",
                    f"Write the card to: {layout.card_draft}",
                    f"Kinds: {kinds}",
                    "",
                    "Card template:",
                    "",
                    template.value.replace("{id}", item.anchor.bead_id).strip(),
                ]
            )
        )
    )


def _context_quote_errors(item: Item, card: cards.Card) -> Result[list[str], str]:
    """Check the card's quoted code against the worktree, which must be untouched.

    A dirty worktree would let code the cutter wrote pass as existing code.
    """
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    clean = gitops.is_clean(workdir.value)
    if isinstance(clean, Err):
        return clean
    if not clean.value:
        return Err(f"the cutter must change nothing, but {workdir.value} has changes; remove them and run this again")
    known = gitops.tracked_lines(workdir.value)
    if isinstance(known, Err):
        return known
    return Ok(cards.unquoted_context_lines(card, known.value))


def cut_card_finish(ctx: Ctx, blocked: str | None) -> Outcome:
    """Validate and seal the cutter's card, then close the step.

    Returns an error listing every problem when the card is invalid; the step
    stays open so the cutter can fix the card and run this again.
    """
    found = _claimed_step(ctx, "cut-card")
    if isinstance(found, Err):
        return found
    item = found.value
    if blocked is not None:
        if not blocked.strip():
            return Err("--blocked needs a reason")
        recorded = ctx.gc.set_metadata(item.anchor.bead_id, {"lite.result": "uncuttable"})
        if isinstance(recorded, Err):
            return recorded
        closed = _close_step(ctx, item.step, "fail", f"the work bead cannot become a card: {blocked.strip()}")
        return closed if isinstance(closed, Err) else Ok(Done("Closed: the item fails as uncuttable.", drain=True))
    layout = _layout(ctx, item)
    draft = _read(layout.card_draft)
    if isinstance(draft, Err):
        return draft
    parsed = cards.parse(draft.value, require_checklist=False)
    if isinstance(parsed, Err):
        return Err("fix the card and run this again:\n- " + "\n- ".join(parsed.error))
    if parsed.value.card_id != item.anchor.bead_id:
        return Err(f"the card id must be {item.anchor.bead_id}, not {parsed.value.card_id}")
    quoted = _context_quote_errors(item, parsed.value)
    if isinstance(quoted, Err):
        return quoted
    if quoted.value:
        return Err("fix the card and run this again:\n- " + "\n- ".join(quoted.value))
    checklist = _read(cards.checklist_path(ctx.env.pack_dir, parsed.value.kind))
    if isinstance(checklist, Err):
        return checklist
    sealed = cards.seal(draft.value, checklist.value)
    if isinstance(sealed, Err):
        return Err("fix the card and run this again:\n- " + "\n- ".join(sealed.error))
    written = _write(layout.card, sealed.value)
    if isinstance(written, Err):
        return written
    recorded = ctx.gc.set_metadata(item.anchor.bead_id, {"lite.kind": parsed.value.kind.value})
    if isinstance(recorded, Err):
        return recorded
    closed = _close_step(ctx, item.step, "pass", f"sealed {parsed.value.kind.value} card {layout.card}")
    return closed if isinstance(closed, Err) else Ok(Done(f"Card sealed at {layout.card}.", drain=True))


# --- attempt -----------------------------------------------------------------

_LOWER = {Tier.T2: Tier.T1, Tier.T3: Tier.T2}
MAX_SUBJECT_LENGTH = 72


def attempt_start(ctx: Ctx) -> Outcome:
    """Reset the worktree to the item's base and print the card and prior findings."""
    found = _claimed_step(ctx, "attempt")
    if isinstance(found, Err):
        return found
    item = found.value
    tier_result = step_tier(item.step)
    if isinstance(tier_result, Err):
        return tier_result
    tier = tier_result.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    base = item.anchor.meta("lite.base_commit")
    if not base:
        return Err(f"source anchor {item.anchor.bead_id} has no lite.base_commit")
    card = _sealed_card(ctx, item)
    if isinstance(card, Err):
        return card
    reset = gitops.reset_to(workdir.value, base)
    if isinstance(reset, Err):
        return reset
    layout = _layout(ctx, item)
    lines = [
        f"Attempt {tier.value.upper()} for {item.anchor.bead_id}.",
        f"Worktree (work only here): {workdir.value}",
        f"Card (your whole task): {layout.card}",
        f"Files you may change: {', '.join(card.value.files)}",
    ]
    lower = _LOWER.get(tier)
    if lower is not None:
        lines += [
            "",
            f"A {lower.value.upper()} attempt was rejected. The worktree is reset to the base commit.",
            f"Why it was rejected: {layout.findings(lower)}",
            f"Its diff, for reference only: {layout.diff(lower)}",
            "Do not reapply that diff blindly; fix what the findings name.",
        ]
    lines += [
        "",
        "When every done_when command passes, run:",
        '  gc superpowers-lite attempt-finish --summary "<one paragraph: what you changed and why>"',
        "If the card cannot be done as written, run:",
        '  gc superpowers-lite attempt-finish --blocked "<what stops you>"',
        "Do not commit, push or touch beads yourself; attempt-finish does it.",
    ]
    return Ok(Done("\n".join(lines)))


def _attempt_message(bead_id: str, tier: Tier, summary: str) -> str:
    """Build an attempt's commit message: a subject of at most 72 characters, the summary, the trailer.

    The ``Bead:`` trailer ties the code to the task's evidence, so it must sit
    alone in the last paragraph, where git reads trailers.
    """
    text = summary.strip()
    subject = f"{bead_id} ({tier.value}): {text.splitlines()[0]}"[:MAX_SUBJECT_LENGTH].rstrip()
    return f"{subject}\n\n{text}\n\nBead: {bead_id}\n"


def attempt_finish(ctx: Ctx, summary: str | None, blocked: str | None) -> Outcome:
    """Commit the attempt, write its report and close the attempt step."""
    if (summary is None) == (blocked is None):
        return Err("pass exactly one of --summary or --blocked")
    text = (summary if summary is not None else blocked) or ""
    if not text.strip():
        return Err("the summary or blocker must not be empty")
    found = _claimed_step(ctx, "attempt")
    if isinstance(found, Err):
        return found
    item = found.value
    tier_result = step_tier(item.step)
    if isinstance(tier_result, Err):
        return tier_result
    tier = tier_result.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    status = reports.Status.DONE if summary is not None else reports.Status.BLOCKED
    commit = ""
    if status is reports.Status.DONE:
        made = gitops.commit_all(workdir.value, _attempt_message(item.anchor.bead_id, tier, text))
        if isinstance(made, Err):
            return made
        commit = made.value or ""
    layout = _layout(ctx, item)
    rendered = reports.render(reports.Report(item.anchor.bead_id, tier, status, commit, text))
    written = _write(layout.report(tier), rendered)
    if isinstance(written, Err):
        return written
    closed = _close_step(
        ctx, item.step, "pass", f"{tier.value} attempt {status.value}",
        {"lite.attempt_status": status.value, "lite.attempt_commit": commit},
    )
    return closed if isinstance(closed, Err) else Ok(Done(f"Attempt recorded ({status.value}).", drain=True))


# --- verify and verdict ------------------------------------------------------


def _record_decision(ctx: Ctx, item: Item, tier: Tier, decision: Decision, why: str) -> Result[None, str]:
    values = {f"lite.attempt.{tier.value}": ("approved" if decision.action is Action.LAND else f"rejected: {why}")}
    if decision.action is Action.LAND:
        values["lite.passed_tier"] = tier.value
    if decision.action is Action.BLOCKED:
        values["lite.result"] = "blocked"
    recorded = ctx.gc.set_metadata(item.anchor.bead_id, values)
    if isinstance(recorded, Err):
        return recorded
    if decision.action is Action.T3:
        body = (
            f"{item.anchor.bead_id} ({item.anchor.title}) failed at t1 and t2: {why}\n"
            f"Findings: {_layout(ctx, item).findings(tier)}\n"
            f"Approve a t3 attempt with: gc superpowers-lite approve --rig {ctx.env.rig} {item.anchor.bead_id}\n"
            "Leave it to keep the item waiting."
        )
        sent = ctx.gc.run("mail", "send", "human", "-s", f"t3 approval needed: {item.anchor.bead_id}", "-m", body)
        if isinstance(sent, Err):
            log.warning("could not mail human about the t3 gate: %s", sent.error)
    return Ok(None)


def _close_verify(ctx: Ctx, item: Item, tier: Tier, verdict: Verdict, why: str) -> Outcome:
    decision = decide(tier, verdict)
    recorded = _record_decision(ctx, item, tier, decision, why)
    if isinstance(recorded, Err):
        return recorded
    closed = _close_step(
        ctx, item.step, decision.outcome, f"{tier.value} {verdict.value}: {why}"[:500],
        {"gc.output_json": decision.output_json, "lite.verdict": verdict.value},
    )
    if isinstance(closed, Err):
        return closed
    return Ok(Done(f"Verdict recorded: {verdict.value}; next: {decision.action.value}.", drain=True))


def _report_check(layout: Layout, tier: Tier, card_id: str) -> tuple[checks.CheckResult, reports.Report | None]:
    text = _read(layout.report(tier))
    if isinstance(text, Err):
        return checks.CheckResult("report-valid", False, (text.error,)), None
    parsed = reports.parse(text.value)
    if isinstance(parsed, Err):
        return checks.CheckResult("report-valid", False, (parsed.error,)), None
    if parsed.value.tier is not tier or parsed.value.card_id != card_id:
        return checks.CheckResult("report-valid", False, ("the report is for another tier or card",)), None
    return checks.CheckResult("report-valid", True, ()), parsed.value


def _findings_text(tier: Tier, results: list[checks.CheckResult], extra: str = "") -> str:
    lines = [f"# Why the {tier.value} attempt was rejected", ""]
    for result in results:
        if not result.passed:
            lines.append(f"## {result.name}")
            lines += [f"- {d}" for d in result.details]
            lines.append("")
    if extra:
        lines += ["## review", extra.strip(), ""]
    return "\n".join(lines)


def verify(ctx: Ctx) -> Outcome:
    """Run the checks on an attempt; reject it outright or hand it to review.

    An error that stops the checks from running closes the step as failed.
    """
    found = _claimed_step(ctx, "verify")
    if isinstance(found, Err):
        return found
    result = _verify(ctx, found.value)
    return _fail(ctx, found.value.step, result.error) if isinstance(result, Err) else result


def _verify(ctx: Ctx, item: Item) -> Outcome:
    tier_result = step_tier(item.step)
    if isinstance(tier_result, Err):
        return tier_result
    tier = tier_result.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    card = _sealed_card(ctx, item)
    if isinstance(card, Err):
        return card
    layout = _layout(ctx, item)
    base = item.anchor.meta("lite.base_commit")
    report_result, report = _report_check(layout, tier, item.anchor.bead_id)
    results = [report_result]
    if report is not None and report.status is reports.Status.BLOCKED:
        results.append(checks.CheckResult("executor", False, (f"the executor reported a blocker: {report.summary}",)))
    else:
        clean = gitops.is_clean(workdir.value)
        if isinstance(clean, Err):
            return clean
        if not clean.value:
            results.append(checks.CheckResult("worktree-clean", False, ("the attempt left uncommitted changes",)))
        changes = gitops.diff(workdir.value, base)
        if isinstance(changes, Err):
            return changes
        saved = _write(layout.diff(tier), changes.value.full)
        if isinstance(saved, Err):
            return saved
        parsed = checks.parse_name_status(changes.value.name_status)
        if not parsed:
            results.append(checks.CheckResult("diff-scope", False, ("the attempt changed nothing",)))
        results.append(checks.diff_scope(parsed, card.value.files))
        results.append(checks.tests_intact(parsed, changes.value.unified))
        head = gitops.rev(workdir.value, "HEAD")
        if isinstance(head, Err):
            return head
        results.append(checks.card_done(card.value.done_when, workdir.value, DONE_WHEN_TIMEOUT_SECONDS))
        # done_when commands leave build products (__pycache__, coverage files)
        # that would make land refuse the worktree as dirty.
        residue = gitops.is_clean(workdir.value)
        if isinstance(residue, Ok) and not residue.value:
            log.info("done_when left changes in %s; restoring %s", workdir.value, head.value)
        restored = gitops.reset_to(workdir.value, head.value)
        if isinstance(restored, Err):
            return restored
    summary = {r.name: ("pass" if r.passed else "fail") for r in results}
    log.info("checks for %s %s: %s", item.anchor.bead_id, tier.value, summary)
    failed = [r for r in results if not r.passed]
    if failed:
        written = _write(layout.findings(tier), _findings_text(tier, results))
        if isinstance(written, Err):
            return written
        why = "failed checks: " + ", ".join(r.name for r in failed)
        return _close_verify(ctx, item, tier, Verdict.REJECT, why)
    marked = ctx.gc.set_metadata(item.step.bead_id, {"lite.checks": "passed", "lite.checks_at": _now()})
    if isinstance(marked, Err):
        return marked
    return Ok(
        Done(
            "\n".join(
                [
                    f"Every check passed for the {tier.value} attempt on {item.anchor.bead_id}.",
                    f"Card: {layout.card}",
                    f"Diff: {layout.diff(tier)}",
                    f"Executor report: {layout.report(tier)}",
                    "",
                    "Review the diff against the card's Goal, Steps, Out of scope and Checklist.",
                    "Approve when the change does what the card asks and nothing else:",
                    "  gc superpowers-lite verdict approve",
                    "Otherwise name each problem, with file and line:",
                    '  gc superpowers-lite verdict reject --reason "<problems>"',
                ]
            )
        )
    )


def verdict(ctx: Ctx, choice: Verdict, reason: str | None) -> Outcome:
    """Record the reviewer's verdict on an attempt whose checks passed."""
    if choice is Verdict.REJECT and not (reason or "").strip():
        return Err("a rejection needs --reason naming each problem")
    found = _claimed_step(ctx, "verify")
    if isinstance(found, Err):
        return found
    item = found.value
    tier_result = step_tier(item.step)
    if isinstance(tier_result, Err):
        return tier_result
    tier = tier_result.value
    if item.step.meta("lite.checks") != "passed":
        return Err("run `gc superpowers-lite verify` first; a verdict needs passing checks")
    layout = _layout(ctx, item)
    text = (reason or "approved").strip()
    review = _write(layout.attempt_dir(tier) / "review.md", f"# {choice.value}\n\n{text}\n")
    if isinstance(review, Err):
        return review
    if choice is Verdict.REJECT:
        written = _write(layout.findings(tier), _findings_text(tier, [], text))
        if isinstance(written, Err):
            return written
    return _close_verify(ctx, item, tier, choice, "review approved" if choice is Verdict.APPROVE else f"review: {text}")


# --- approval, land, close ---------------------------------------------------


def approval(ctx: Ctx) -> Outcome:
    """Close the t3 approval step once its human gate has been closed."""
    found = _claimed_step(ctx, "approval")
    if isinstance(found, Err):
        return found
    closed = _close_step(ctx, found.value.step, "pass", "a human approved the t3 attempt")
    return closed if isinstance(closed, Err) else Ok(Done("Approval recorded.", drain=True))


def approve(gc: Gc, anchor_id: str) -> Outcome:
    """Human command: close the open t3 gate of the item serving ``anchor_id``.

    Needs no agent environment, so a human can run it from any shell; ``gc``
    names the rig whose store holds the item.
    """
    roots = gc.bd(
        "list", "--metadata-field", f"lite.anchor_id={anchor_id}", "--all",
        "--include-ephemeral", "--limit", "0", "--json",
    )
    if isinstance(roots, Err):
        return roots
    try:
        root_ids = [r["id"] for r in json.loads(roots.value) if r.get("status") != "closed"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return Err("gc bd list printed unexpected JSON")
    gates: list[str] = []
    for root_id in root_ids:
        listed = gc.bd(
            "list", "--metadata-field", f"gc.root_bead_id={root_id}", "--type", "gate",
            "--include-gates", "--include-ephemeral", "--status", "open,in_progress", "--limit", "0", "--json",
        )
        if isinstance(listed, Err):
            return listed
        try:
            gates += [g["id"] for g in json.loads(listed.value)]
        except (json.JSONDecodeError, KeyError, TypeError):
            return Err("gc bd list printed unexpected JSON")
    if len(gates) != 1:
        return Err(f"expected one open t3 gate for {anchor_id}, found {len(gates)}: {', '.join(gates)}")
    closed = gc.close(gates[0], f"t3 attempt approved for {anchor_id}")
    return closed if isinstance(closed, Err) else Ok(Done(f"Approved: closed gate {gates[0]}."))


def land(ctx: Ctx) -> Outcome:
    """Fast-forward the item's target branch to the approved attempt."""
    found = _claimed_step(ctx, "land")
    if isinstance(found, Err):
        return found
    item = found.value
    anchor = item.anchor
    if not anchor.meta("lite.passed_tier"):
        return _fail(ctx, item.step, f"{anchor.bead_id} has no approved attempt (lite.passed_tier)")
    workdir = _workdir(item)
    target, base = anchor.meta("target"), anchor.meta("lite.base_commit")
    if isinstance(workdir, Err) or not target or not base:
        return _fail(ctx, item.step, f"{anchor.bead_id} lacks work_dir, target or lite.base_commit")
    landed = gitops.land(ctx.env.rig_root, workdir.value, target, base, f"land {item.root.bead_id}")
    if isinstance(landed, Err):
        recorded = ctx.gc.set_metadata(anchor.bead_id, {"lite.result": "land-refused"})
        if isinstance(recorded, Err):
            log.warning("could not record the refused land on %s: %s", anchor.bead_id, recorded.error)
        return _fail(ctx, item.step, f"refused: {landed.error}")
    recorded = ctx.gc.set_metadata(anchor.bead_id, {"lite.landed_commit": landed.value.commit, "lite.result": "landed"})
    if isinstance(recorded, Err):
        return recorded
    closed = _close_step(ctx, item.step, "pass", landed.value.message)
    return closed if isinstance(closed, Err) else Ok(Done(landed.value.message, drain=True))


def _fail(ctx: Ctx, step: Bead, reason: str) -> Outcome:
    closed = _close_step(ctx, step, "fail", reason)
    return closed if isinstance(closed, Err) else Ok(Done(f"Step failed: {reason}", drain=True))


def close_anchor(ctx: Ctx) -> Outcome:
    """Close the work bead once its change has landed."""
    found = _claimed_step(ctx, "close-anchor")
    if isinstance(found, Err):
        return found
    item = found.value
    anchor = item.anchor
    landed, target = anchor.meta("lite.landed_commit"), anchor.meta("target")
    if not landed or not target:
        return _fail(ctx, item.step, f"{anchor.bead_id} has no lite.landed_commit or target")
    if not gitops.is_ancestor(ctx.env.rig_root, landed, f"refs/heads/{target}"):
        return _fail(ctx, item.step, f"refs/heads/{target} does not contain {landed}")
    closed_anchor = ctx.gc.set_metadata(anchor.bead_id, {"gc.outcome": "pass"})
    if isinstance(closed_anchor, Err):
        return closed_anchor
    shut = ctx.gc.close(anchor.bead_id, f"landed {landed} on {target}")
    if isinstance(shut, Err):
        return _fail(ctx, item.step, f"could not close {anchor.bead_id}: {shut.error}")
    after = ctx.gc.show(anchor.bead_id)
    if isinstance(after, Err) or after.value.status != "closed":
        return _fail(ctx, item.step, f"{anchor.bead_id} did not read back as closed")
    closed = _close_step(ctx, item.step, "pass", f"closed {anchor.bead_id}: landed {landed} on {target}")
    return closed if isinstance(closed, Err) else Ok(Done(f"Closed {anchor.bead_id}.", drain=True))
