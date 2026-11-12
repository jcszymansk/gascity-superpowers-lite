"""The pack commands, one function per ``gc superpowers-lite <name>``.

Agents never manage beads themselves. Each command checks that the claimed
step is the kind it expects (``lite.step``), does its deterministic work, and
closes only that step. Per-item state lives on the source anchor.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from litetools import card as cards
from litetools import checks, donewhen, gitops
from litetools import report as reports
from litetools.context import (
    CardLayout,
    CardRef,
    Env,
    Item,
    Layout,
    card_ref,
    claimed_bead_id,
    forget_claim,
    layout_for,
    resolve_item,
    save_claim,
    step_attempt,
)
from litetools.gc import Bead, Gc
from litetools.ladder import Action, Attempt, Decision, Tier, Verdict, decide, highest, parse_attempt
from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

DONE_WHEN_TIMEOUT_SECONDS = 15 * 60
OPEN_STATUSES = ("open", "in_progress")
_DRAFT_NAME = re.compile(r"(?P<number>[1-9][0-9]*)\.md")


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


@dataclass(frozen=True, slots=True)
class CardScope:
    """The card a claimed attempt or verify step serves.

    Attributes:
        ref: Which card, of how many.
        files: The card's artifact files.
        base: The commit the card's work starts from: the item's base for the
            first card, the previous card's approved attempt for the others.
        card: The sealed card.
    """

    ref: CardRef
    files: CardLayout
    base: str
    card: cards.Card


def _card_base_key(number: int) -> str:
    return "lite.base_commit" if number == 1 else f"lite.card.{number}.base_commit"


def _card_scope(ctx: Ctx, item: Item) -> Result[CardScope, str]:
    """Resolve the claimed step's card and pin it on the step.

    Pinning keeps the step on its card when it runs again after the anchor
    moved on to the next card, as a verify step does when its close fails
    after its decision was recorded.
    """
    ref = card_ref(item.anchor, item.step)
    if isinstance(ref, Err):
        return ref
    base = item.anchor.meta(_card_base_key(ref.value.number))
    if not base:
        return Err(f"source anchor {item.anchor.bead_id} has no {_card_base_key(ref.value.number)}")
    files = _layout(ctx, item).card(ref.value)
    card = _sealed_card(files.card, item.anchor.bead_id)
    if isinstance(card, Err):
        return card
    if not ref.value.legacy and item.step.meta("lite.card") != str(ref.value.number):
        pinned = ctx.gc.set_metadata(item.step.bead_id, {"lite.card": str(ref.value.number)})
        if isinstance(pinned, Err):
            return pinned
    log.info("step %s works on %s of %s", item.step.bead_id, ref.value.label, item.anchor.bead_id)
    return Ok(CardScope(ref.value, files, base, card.value))


def _sealed_card(path: Path, anchor_id: str) -> Result[cards.Card, str]:
    text = _read(path)
    if isinstance(text, Err):
        return text
    parsed = cards.parse(text.value, require_checklist=True)
    if isinstance(parsed, Err):
        return Err("the sealed card is invalid: " + "; ".join(parsed.error))
    if parsed.value.card_id != anchor_id:
        return Err(f"the card is for {parsed.value.card_id}, not {anchor_id}")
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


def _unlanded_blockers(anchor: Bead) -> list[str]:
    """Describe each ``blocks`` predecessor of ``anchor`` that has not landed.

    A predecessor counts as done when it is closed and lite did not record a
    failed result on it; a bead closed by a human without lite counts as done.
    The drain starts an item only after its predecessors' items finish, so an
    open predecessor here is one whose item failed.
    """
    return [
        f"{b.bead_id} ({b.status}, lite.result={b.meta('lite.result') or 'none'})"
        for b in anchor.blocked_by
        if b.status != "closed" or b.meta("lite.result") not in ("", "landed")
    ]


def _prepare(ctx: Ctx, item: Item) -> Result[str, str]:
    rig = ctx.env.rig_root
    anchor = item.anchor
    unlanded = _unlanded_blockers(anchor)
    if unlanded:
        log.warning("item %s: predecessors did not land: %s", anchor.bead_id, ", ".join(unlanded))
        marked = ctx.gc.set_metadata(anchor.bead_id, {"lite.result": "skipped"})
        if isinstance(marked, Err):
            return marked
        return Err(f"skipped: {anchor.bead_id} is blocked by work that did not land: {', '.join(unlanded)}")
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
    submodules = gitops.init_submodules(worktree)
    if isinstance(submodules, Err):
        return submodules
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
    """Print the work bead and where to write its cards."""
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
    example = _read(ctx.env.pack_dir / "assets" / "templates" / "card-example.md")
    if isinstance(example, Err):
        return example
    layout = _layout(ctx, item)
    # The artifact directory belongs to the work bead, so a bead slung again
    # finds the drafts of its earlier run there. A restarted cutter session runs
    # this again on the same step and must keep the drafts it already wrote.
    if item.step.meta("lite.cut_started") != "true":
        cleared = _clear_drafts(layout)
        if isinstance(cleared, Err):
            return cleared
        marked = ctx.gc.set_metadata(item.step.bead_id, {"lite.cut_started": "true"})
        if isinstance(marked, Err):
            return marked
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
                    f"Write the cards to: {layout.drafts}/",
                    f"  one card: {layout.draft(1)}",
                    f"  several, in the order they must be done: {layout.draft(1).name}, "
                    f"{layout.draft(2).name}, ... (at most {cards.MAX_CARDS})",
                    f"Kinds: {kinds}",
                    "",
                    "Card template:",
                    "",
                    template.value.replace("{id}", item.anchor.bead_id).strip(),
                    "",
                    "Example card, from another project. Copy its shape and level of detail, not its content:",
                    "",
                    example.value.strip(),
                ]
            )
        )
    )


def _clear_drafts(layout: Layout) -> Result[None, str]:
    """Remove the drafts an earlier run of the same work bead left behind."""
    try:
        if layout.drafts.is_dir():
            stale = sorted(layout.drafts.iterdir())
            if stale:
                log.info("removing %d stale drafts from %s", len(stale), layout.drafts)
            shutil.rmtree(layout.drafts)
    except OSError as error:
        return Err(f"could not clear the old drafts in {layout.drafts}: {error}")
    return Ok(None)


def _draft_paths(layout: Layout) -> Result[list[Path], list[str]]:
    """Return the cutter's drafts in card order, or every problem with the drafts directory.

    The drafts must be named ``1.md`` to ``<n>.md`` with no gap, because their
    numbers are the order the cards are done in.
    """
    try:
        entries = sorted(layout.drafts.iterdir()) if layout.drafts.is_dir() else []
    except OSError as error:
        return Err([f"could not list {layout.drafts}: {error}"])
    numbered: dict[int, Path] = {}
    errors: list[str] = []
    for entry in entries:
        match = _DRAFT_NAME.fullmatch(entry.name)
        if match is None or not entry.is_file():
            errors.append(f"{entry} is not a card draft; name the drafts 1.md, 2.md, ... and remove anything else")
        else:
            numbered[int(match.group("number"))] = entry
    if not numbered and not errors:
        errors.append(f"no card drafts in {layout.drafts}; write the first card to {layout.draft(1)}")
    if len(numbered) > cards.MAX_CARDS:
        errors.append(
            f"{len(numbered)} cards; the cap is {cards.MAX_CARDS}. A bead this large needs lite-build, "
            "so report it with --blocked"
        )
    gaps = sorted(set(range(1, max(numbered, default=0) + 1)) - set(numbered))
    if gaps:
        errors.append("the drafts must be numbered from 1 with no gap; missing " + ", ".join(f"{n}.md" for n in gaps))
    return Err(errors) if errors else Ok([numbered[n] for n in sorted(numbered)])


def _context_quote_errors(item: Item, drafts: list[cards.Card]) -> Result[list[str], str]:
    """Check every card's quoted code against the worktree, which must be untouched.

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
    return Ok(
        [
            f"card {number}: {error}"
            for number, card in enumerate(drafts, start=1)
            for error in cards.unquoted_context_lines(card, known.value)
        ]
    )


def _fix_cards(errors: list[str]) -> Outcome:
    return Err("fix the cards and run this again:\n- " + "\n- ".join(errors))


def _kinds_metadata(sealed: list[cards.Card]) -> dict[str, str]:
    """The kind metadata of an item: ``lite.kind`` lists each kind once, in card order."""
    kinds = list(dict.fromkeys(card.kind.value for card in sealed))
    values = {"lite.kind": ",".join(kinds)}
    if len(sealed) > 1:
        values |= {f"lite.card.{n}.kind": card.kind.value for n, card in enumerate(sealed, start=1)}
    return values


def cut_card_finish(ctx: Ctx, blocked: str | None) -> Outcome:
    """Validate and seal the cutter's cards, then close the step.

    Returns an error listing every problem in every card when any is invalid;
    the step stays open so the cutter can fix the cards and run this again.
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
        closed = _close_step(ctx, item.step, "fail", f"the work bead cannot become cards: {blocked.strip()}")
        return closed if isinstance(closed, Err) else Ok(Done("Closed: the item fails as uncuttable.", drain=True))
    layout = _layout(ctx, item)
    paths = _draft_paths(layout)
    if isinstance(paths, Err):
        return _fix_cards(paths.error)
    texts: list[str] = []
    parsed: list[cards.Card] = []
    errors: list[str] = []
    for number, path in enumerate(paths.value, start=1):
        text = _read(path)
        if isinstance(text, Err):
            return text
        card = cards.parse(text.value, require_checklist=False)
        if isinstance(card, Err):
            errors += [f"card {number}: {error}" for error in card.error]
            continue
        if card.value.card_id != item.anchor.bead_id:
            errors.append(f"card {number}: the card id must be {item.anchor.bead_id}, not {card.value.card_id}")
        texts.append(text.value)
        parsed.append(card.value)
    if errors:
        return _fix_cards(errors)
    quoted = _context_quote_errors(item, parsed)
    if isinstance(quoted, Err):
        return quoted
    if quoted.value:
        return _fix_cards(quoted.value)
    sealed_texts: list[str] = []
    for number, (draft_text, draft_card) in enumerate(zip(texts, parsed, strict=True), start=1):
        checklist = _read(cards.checklist_path(ctx.env.pack_dir, draft_card.kind))
        if isinstance(checklist, Err):
            return checklist
        sealed = cards.seal(draft_text, checklist.value)
        if isinstance(sealed, Err):
            return _fix_cards([f"card {number}: {error}" for error in sealed.error])
        sealed_texts.append(sealed.value)
    total = len(sealed_texts)
    for number, sealed_text in enumerate(sealed_texts, start=1):
        written = _write(layout.card(CardRef(number, total, False)).card, sealed_text)
        if isinstance(written, Err):
            return written
    recorded = ctx.gc.set_metadata(
        item.anchor.bead_id, {"lite.cards": str(total), "lite.card": "1", **_kinds_metadata(parsed)}
    )
    if isinstance(recorded, Err):
        return recorded
    log.info("item %s: sealed %d cards in %s", item.anchor.bead_id, total, layout.root / "cards")
    what = "1 card" if total == 1 else f"{total} cards"
    closed = _close_step(ctx, item.step, "pass", f"sealed {what} ({_kinds_metadata(parsed)['lite.kind']}) in {layout.root / 'cards'}")
    return closed if isinstance(closed, Err) else Ok(Done(f"Sealed {what} in {layout.root / 'cards'}.", drain=True))


# --- attempt -----------------------------------------------------------------

MAX_SUBJECT_LENGTH = 72


def _rejected_attempt(item: Item, ref: CardRef) -> Result[Attempt | None, str]:
    """Return the card's last rejected attempt, or None before its first rejection."""
    key = item.anchor.meta(f"{ref.prefix}last_rejected")
    if not key:
        return Ok(None)
    parsed = parse_attempt(key)
    return parsed if isinstance(parsed, Err) else Ok(parsed.value)


def _start_commit(layout: CardLayout, attempt: Attempt, previous: Attempt | None, base: str) -> Result[str, str]:
    """Return the commit an attempt starts from: the rejected attempt for a retry, else the card's base."""
    if attempt.round == 1:
        return Ok(base)
    if previous is None or previous.tier is not attempt.tier or previous.round != attempt.round - 1:
        return Err(f"retry {attempt.key} needs a rejected {attempt.tier.value} attempt before it, got {previous}")
    text = _read(layout.report(previous))
    if isinstance(text, Err):
        return text
    report = reports.parse(text.value)
    if isinstance(report, Err):
        return Err(f"the report of {previous.key} is invalid: {report.error}")
    return Ok(report.value.commit or base)


def attempt_start(ctx: Ctx) -> Outcome:
    """Prepare the worktree and print the card and the last rejection's findings.

    A first attempt at a tier starts from the card's base; a retry starts from
    the attempt it retries.
    """
    found = _claimed_step(ctx, "attempt")
    if isinstance(found, Err):
        return found
    item = found.value
    attempt_result = step_attempt(item.step)
    if isinstance(attempt_result, Err):
        return attempt_result
    attempt = attempt_result.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    scope = _card_scope(ctx, item)
    if isinstance(scope, Err):
        return scope
    ref, files = scope.value.ref, scope.value.files
    previous = _rejected_attempt(item, ref)
    if isinstance(previous, Err):
        return previous
    start = _start_commit(files, attempt, previous.value, scope.value.base)
    if isinstance(start, Err):
        return start
    lines = [
        f"Attempt {attempt.key.upper()} for {item.anchor.bead_id}" + ("." if ref.total == 1 else f", {ref.label}."),
        f"Worktree (work only here): {workdir.value}",
        f"Card (your whole task): {files.card}",
        f"Files the card expects you to change: {', '.join(scope.value.card.files)}",
    ]
    if ref.number > 1:
        lines += [
            "",
            f"The work bead was cut into {ref.total} cards, done in order. Cards 1 to {ref.number - 1} are",
            "done and committed in the worktree: build on them, and change their work only where",
            "your card says so.",
        ]
    # gc restarts a session that sits idle while it holds this step, and the
    # new session starts here again: resetting would discard its work.
    if item.step.meta("lite.attempt_started") == "true":
        log.info("resuming %s %s without a reset", item.anchor.bead_id, attempt.key)
        lines += [
            "",
            "This attempt was already started by a session that was restarted. The worktree is",
            "not reset: it holds that session's uncommitted work. Read `git status` and `git diff`",
            "in it, then continue from there.",
        ]
        lines += _attempt_finish_lines()
        return Ok(Done("\n".join(lines)))
    reset = gitops.reset_to(workdir.value, start.value)
    if isinstance(reset, Err):
        return reset
    marked = ctx.gc.set_metadata(item.step.bead_id, {"lite.attempt_started": "true"})
    if isinstance(marked, Err):
        return marked
    where = "the base commit" if ref.number == 1 else f"where {ref.label} starts"
    if attempt.round > 1 and previous.value is not None:
        lines += [
            "",
            f"This is a retry. Your {previous.value.key} attempt was rejected, and the worktree holds it",
            f"(commit {start.value[:12]}). Read why: {files.findings(previous.value)}",
            "Fix what the findings name and keep what already works; do not start over.",
        ]
    elif previous.value is not None:
        lines += [
            "",
            f"A {previous.value.key} attempt was rejected. The worktree is reset to {where}.",
            f"Why it was rejected: {files.findings(previous.value)}",
            f"Its diff, for reference only: {files.diff(previous.value)}",
            "Do not reapply that diff blindly; fix what the findings name.",
        ]
    lines += _attempt_finish_lines()
    return Ok(Done("\n".join(lines)))


def _attempt_finish_lines() -> list[str]:
    return [
        "",
        "Run builds and tests through `gc superpowers-lite run '<command>'`.",
        "When every done_when command passes, run:",
        '  gc superpowers-lite attempt-finish --summary "<one paragraph: what you changed and why>"',
        "If the card cannot be done as written, run:",
        '  gc superpowers-lite attempt-finish --blocked "<what stops you>"',
        "Do not commit, push or touch beads yourself; attempt-finish does it.",
    ]


def run(ctx: Ctx, command: str) -> Outcome:
    """Run a build or test command for the claimed attempt in a runner that outlives the session.

    The command runs in the item worktree. A call waits under two minutes; when
    the command is still running it says so, and the same call again attaches
    to that run. A finished run is reported once; the next call starts afresh.
    """
    if not command.strip():
        return Err("run needs a command")
    found = _claimed_step(ctx, "attempt")
    if isinstance(found, Err):
        return found
    item = found.value
    attempt = step_attempt(item.step)
    if isinstance(attempt, Err):
        return attempt
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    scope = _card_scope(ctx, item)
    if isinstance(scope, Err):
        return scope
    key = hashlib.sha256(command.encode()).hexdigest()[:16]
    state = donewhen.State(scope.value.files.attempt_dir(attempt.value) / "runs" / key)
    spec = donewhen.Spec("", (command,), workdir.value, DONE_WHEN_TIMEOUT_SECONDS)
    waited = donewhen.await_outcomes(state, spec, ctx.env.verify_wait_seconds)
    if isinstance(waited, Err):
        return waited
    if waited.value is None:
        return Ok(Done(_run_still_running_text(command, state)))
    outcome = waited.value[0]
    donewhen.forget(state)
    if outcome.exit_code is None:
        head = f"Timed out after {DONE_WHEN_TIMEOUT_SECONDS}s: {command}"
    else:
        head = f"Exit {outcome.exit_code}{' (passed)' if outcome.passed else ' (failed)'}: {command}"
    return Ok(Done("\n".join([head, "", outcome.output])))


def _run_still_running_text(command: str, state: donewhen.State) -> str:
    return "\n".join(
        [
            f"Still running in the background, and it survives this session: {command}",
            f"Its log: {state.log_file}",
            "Run the same `gc superpowers-lite run` again now, and keep doing so until it prints",
            "the exit status. Do not end your turn while it runs: gc restarts a session that sits",
            "idle at its prompt while it holds this step. If you changed files after it started,",
            "run it once more after it finishes.",
        ]
    )


def _attempt_label(ref: CardRef, attempt: Attempt) -> str:
    """Name an attempt in commit subjects: ``t1.2``, or ``2/3 t1.2`` on a split item."""
    return attempt.key if ref.total == 1 else f"{ref.number}/{ref.total} {attempt.key}"


def _attempt_message(bead_id: str, label: str, summary: str) -> str:
    """Build an attempt's commit message: a subject of at most 72 characters, the summary, the trailer.

    The ``Bead:`` trailer ties the code to the task's evidence, so it must sit
    alone in the last paragraph, where git reads trailers.
    """
    text = summary.strip()
    first_sentence = re.split(r"(?<=[.!?])\s", text.splitlines()[0], maxsplit=1)[0].rstrip(".!?")
    prefix = f"{bead_id} ({label}): "
    subject = prefix + first_sentence
    if len(subject) > MAX_SUBJECT_LENGTH:
        cut = subject[:MAX_SUBJECT_LENGTH]
        last_space = cut.rfind(" ")
        subject = cut[:last_space] if last_space > len(prefix) else cut
    return f"{subject.rstrip()}\n\n{text}\n\nBead: {bead_id}\n"


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
    attempt_result = step_attempt(item.step)
    if isinstance(attempt_result, Err):
        return attempt_result
    attempt = attempt_result.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    scope = _card_scope(ctx, item)
    if isinstance(scope, Err):
        return scope
    status = reports.Status.DONE if summary is not None else reports.Status.BLOCKED
    commit = ""
    if status is reports.Status.DONE:
        message = _attempt_message(item.anchor.bead_id, _attempt_label(scope.value.ref, attempt), text)
        made = gitops.commit_all(workdir.value, message)
        if isinstance(made, Err):
            return made
        commit = made.value or ""
    rendered = reports.render(reports.Report(item.anchor.bead_id, attempt.tier, status, commit, text))
    written = _write(scope.value.files.report(attempt), rendered)
    if isinstance(written, Err):
        return written
    closed = _close_step(
        ctx, item.step, "pass", f"{attempt.key} attempt {status.value}",
        {"lite.attempt_status": status.value, "lite.attempt_commit": commit},
    )
    return closed if isinstance(closed, Err) else Ok(Done(f"Attempt recorded ({status.value}).", drain=True))


# --- verify and verdict ------------------------------------------------------


def _item_passed_tier(item: Item, ref: CardRef, tier: Tier) -> Result[str, str]:
    """Return the tier an item passed at: the most expensive tier any of its cards needed."""
    tiers = [tier]
    for number in range(1, ref.number):
        key = f"lite.card.{number}.passed_tier"
        earlier = next((t for t in Tier if t.value == item.anchor.meta(key)), None)
        if earlier is None:
            return Err(f"{item.anchor.bead_id} has no valid {key}, so card {number} never passed")
        tiers.append(earlier)
    top = highest(tiers)
    return top if isinstance(top, Err) else Ok(top.value.value)


def _approved_commit(files: CardLayout, attempt: Attempt) -> Result[str, str]:
    """Return the commit of an approved attempt, where the next card starts."""
    text = _read(files.report(attempt))
    if isinstance(text, Err):
        return text
    report = reports.parse(text.value)
    if isinstance(report, Err):
        return Err(f"the report of {attempt.key} is invalid: {report.error}")
    if not report.value.commit:
        return Err(f"the approved {attempt.key} attempt has no commit")
    return Ok(report.value.commit)


def _decision_metadata(
    item: Item, scope: CardScope, attempt: Attempt, verdict: Verdict, decision: Decision, why: str
) -> Result[dict[str, str], str]:
    """Return what the anchor records about a verified attempt.

    An approval that leaves cards to do moves the anchor to the next card and
    records where that card starts; the last card's approval records the
    tier the whole item passed at, which ``land`` requires.
    """
    ref = scope.ref
    approved = verdict is Verdict.APPROVE
    values = {f"{ref.prefix}attempt.{attempt.key}": "approved" if approved else f"rejected: {why}"}
    if not approved:
        values[f"{ref.prefix}last_rejected"] = attempt.key
    elif ref.is_last:
        values[f"{ref.prefix}passed_tier"] = attempt.tier.value
        passed = _item_passed_tier(item, ref, attempt.tier)
        if isinstance(passed, Err):
            return passed
        values["lite.passed_tier"] = passed.value
    else:
        commit = _approved_commit(scope.files, attempt)
        if isinstance(commit, Err):
            return commit
        following = ref.number + 1
        values |= {
            f"{ref.prefix}passed_tier": attempt.tier.value,
            "lite.card": str(following),
            _card_base_key(following): commit.value,
        }
    if decision.action is Action.BLOCKED:
        values["lite.result"] = "blocked"
    return Ok(values)


def _record_decision(
    ctx: Ctx, item: Item, scope: CardScope, attempt: Attempt, verdict: Verdict, decision: Decision, why: str
) -> Result[None, str]:
    values = _decision_metadata(item, scope, attempt, verdict, decision, why)
    if isinstance(values, Err):
        return values
    recorded = ctx.gc.set_metadata(item.anchor.bead_id, values.value)
    if isinstance(recorded, Err):
        return recorded
    if decision.action is Action.T3:
        which = "" if scope.ref.total == 1 else f" on {scope.ref.label}"
        body = (
            f"{item.anchor.bead_id} ({item.anchor.title}) failed at t1 and t2{which}: {why}\n"
            f"Findings: {scope.files.findings(attempt)}\n"
            f"Approve a t3 attempt with: gc superpowers-lite approve --rig {ctx.env.rig} {item.anchor.bead_id}\n"
            "Leave it to keep the item waiting."
        )
        sent = ctx.gc.run("mail", "send", "human", "-s", f"t3 approval needed: {item.anchor.bead_id}", "-m", body)
        if isinstance(sent, Err):
            log.warning("could not mail human about the t3 gate: %s", sent.error)
    return Ok(None)


def _close_verify(
    ctx: Ctx, item: Item, scope: CardScope, attempt: Attempt, verdict: Verdict, why: str, retryable: bool = True
) -> Outcome:
    decision = decide(attempt, verdict, retryable, scope.ref.is_last)
    recorded = _record_decision(ctx, item, scope, attempt, verdict, decision, why)
    if isinstance(recorded, Err):
        return recorded
    which = "" if scope.ref.total == 1 else f"{scope.ref.label} "
    closed = _close_step(
        ctx, item.step, decision.outcome, f"{which}{attempt.key} {verdict.value}: {why}"[:500],
        {"gc.output_json": decision.output_json, "lite.verdict": verdict.value},
    )
    if isinstance(closed, Err):
        return closed
    if verdict is Verdict.APPROVE and not scope.ref.is_last:
        next_name = f"t1 on card {scope.ref.number + 1} of {scope.ref.total}"
    else:
        next_name = decision.next_attempt.key if decision.next_attempt is not None else decision.action.value
    return Ok(Done(f"Verdict recorded: {verdict.value}; next: {next_name}.", drain=True))


def _report_check(layout: CardLayout, attempt: Attempt, card_id: str) -> tuple[checks.CheckResult, reports.Report | None]:
    text = _read(layout.report(attempt))
    if isinstance(text, Err):
        return checks.CheckResult("report-valid", False, (text.error,)), None
    parsed = reports.parse(text.value)
    if isinstance(parsed, Err):
        return checks.CheckResult("report-valid", False, (parsed.error,)), None
    if parsed.value.tier is not attempt.tier or parsed.value.card_id != card_id:
        return checks.CheckResult("report-valid", False, ("the report is for another tier or card",)), None
    return checks.CheckResult("report-valid", True, ()), parsed.value


def _findings_text(attempt: Attempt, results: list[checks.CheckResult], extra: str = "") -> str:
    lines = [f"# Why the {attempt.key} attempt was rejected", ""]
    for result in results:
        if not result.passed:
            lines.append(f"## {result.name}")
            lines += [f"- {d}" for d in result.details]
            lines.append("")
    if extra:
        lines += ["## review", extra.strip(), ""]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class QuickChecks:
    """The checks that take seconds, run once per attempt commit.

    Attributes:
        results: Every quick check's result.
        removed: The tests the attempt removes, for the reviewer.
        outside: The files the attempt touches that the card does not list, for the reviewer.
        report: The executor's report, when it parsed.
        blocked: True when the executor reported a blocker instead of a change.
    """

    results: tuple[checks.CheckResult, ...]
    removed: tuple[str, ...]
    outside: tuple[str, ...]
    report: reports.Report | None
    blocked: bool


def _quick_checks(
    ctx: Ctx, item: Item, attempt: Attempt, scope: CardScope, workdir: Path, head: str, state: donewhen.State
) -> Result[QuickChecks, str]:
    """Run the quick checks, or reuse what an earlier verify of this commit saved.

    They are saved because they must see the worktree as the attempt left it:
    once done_when runs, its build products would fail worktree-clean on a
    second verify.
    """
    layout, card, prefix = scope.files, scope.card, scope.ref.prefix
    report_result, report = _report_check(layout, attempt, item.anchor.bead_id)
    blocked = report is not None and report.status is reports.Status.BLOCKED
    saved = _load_quick(state, head)
    if saved is not None:
        log.info("reusing the quick checks of %s %s at %s", item.anchor.bead_id, attempt.key, head)
        return Ok(QuickChecks(saved[0], saved[1], saved[2], report, blocked))
    results = [report_result]
    removed: tuple[str, ...] = ()
    outside: tuple[str, ...] = ()
    if blocked and report is not None:
        results.append(checks.CheckResult("executor", False, (f"the executor reported a blocker: {report.summary}",)))
    else:
        clean = gitops.is_clean(workdir)
        if isinstance(clean, Err):
            return clean
        if not clean.value:
            results.append(checks.CheckResult("worktree-clean", False, ("the attempt left uncommitted changes",)))
        changes = gitops.diff(workdir, scope.base)
        if isinstance(changes, Err):
            return changes
        saved_diff = _write(layout.diff(attempt), changes.value.full)
        if isinstance(saved_diff, Err):
            return saved_diff
        shared = cards.overlap(card, checks.added_lines(changes.value.unified))
        log.info("card overlap for %s %s: %s lines copied from the card", item.anchor.bead_id, attempt.key, shared)
        parsed = checks.parse_name_status(changes.value.name_status)
        touched = len(checks.touched_paths(parsed))
        log.info("%s %s touches %d files", item.anchor.bead_id, attempt.key, touched)
        recorded = ctx.gc.set_metadata(
            item.anchor.bead_id,
            {f"{prefix}card_overlap.{attempt.key}": str(shared), f"{prefix}files_touched.{attempt.key}": str(touched)},
        )
        if isinstance(recorded, Err):
            return recorded
        results.append(checks.non_empty_diff(parsed))
        results.append(checks.no_skip_markers(changes.value.unified))
        removed = checks.removed_tests(parsed, changes.value.unified)
        if removed:
            log.info("%s %s removes tests: %s", item.anchor.bead_id, attempt.key, "; ".join(removed))
        outside = checks.outside_files(parsed, card.files)
        if outside:
            log.info("%s %s touches files the card does not list: %s", item.anchor.bead_id, attempt.key, ", ".join(outside))
    stored = _store_quick(state, head, results, removed, outside)
    if isinstance(stored, Err):
        return stored
    return Ok(QuickChecks(tuple(results), removed, outside, report, blocked))


def _quick_file(state: donewhen.State) -> Path:
    return state.root / "quick.json"


def _load_quick(
    state: donewhen.State, head: str
) -> tuple[tuple[checks.CheckResult, ...], tuple[str, ...], tuple[str, ...]] | None:
    try:
        data = json.loads(_quick_file(state).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("head") != head:
        return None
    raw_results, raw_removed = data.get("results"), data.get("removed")
    # Saved before files outside the card became review input: those runs failed such files
    # in the checks instead, so there is nothing to show the reviewer.
    raw_outside = data.get("outside", [])
    if not isinstance(raw_results, list) or not isinstance(raw_removed, list) or not isinstance(raw_outside, list):
        return None
    results: list[checks.CheckResult] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            return None
        name, passed, details = entry.get("name"), entry.get("passed"), entry.get("details")
        if not isinstance(name, str) or not isinstance(passed, bool) or not isinstance(details, list):
            return None
        results.append(checks.CheckResult(name, passed, tuple(str(d) for d in details)))
    return tuple(results), tuple(str(r) for r in raw_removed), tuple(str(o) for o in raw_outside)


def _store_quick(
    state: donewhen.State,
    head: str,
    results: list[checks.CheckResult],
    removed: tuple[str, ...],
    outside: tuple[str, ...],
) -> Result[None, str]:
    data = {
        "head": head,
        "results": [{"name": r.name, "passed": r.passed, "details": list(r.details)} for r in results],
        "removed": list(removed),
        "outside": list(outside),
    }
    try:
        state.root.mkdir(parents=True, exist_ok=True)
        _quick_file(state).write_text(json.dumps(data, indent=2) + "\n")
    except OSError as error:
        return Err(f"could not save the quick checks in {state.root}: {error}")
    return Ok(None)


def _still_running_text(state: donewhen.State) -> str:
    return "\n".join(
        [
            "The done_when checks are still running in the background; they survive this session.",
            f"Their log: {state.log_file}",
            "Run `gc superpowers-lite verify` again now, and keep doing so until it prints a",
            "result. Do not end your turn while they run:",
            "gc restarts a session that sits idle at its prompt while it holds this step.",
        ]
    )


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
    attempt_result = step_attempt(item.step)
    if isinstance(attempt_result, Err):
        return attempt_result
    attempt = attempt_result.value
    workdir = _workdir(item)
    if isinstance(workdir, Err):
        return workdir
    scope = _card_scope(ctx, item)
    if isinstance(scope, Err):
        return scope
    layout = scope.value.files
    head = gitops.rev(workdir.value, "HEAD")
    if isinstance(head, Err):
        return head
    state = donewhen.State(layout.attempt_dir(attempt) / "checks")
    quick = _quick_checks(ctx, item, attempt, scope.value, workdir.value, head.value, state)
    if isinstance(quick, Err):
        return quick
    results = list(quick.value.results)
    removed = quick.value.removed
    outside = quick.value.outside
    report = quick.value.report
    if not quick.value.blocked:
        spec = donewhen.Spec(head.value, scope.value.card.done_when, workdir.value, DONE_WHEN_TIMEOUT_SECONDS)
        waited = donewhen.await_result(state, spec, ctx.env.verify_wait_seconds)
        if isinstance(waited, Err):
            return waited
        if waited.value is None:
            log.info("done_when for %s %s still running", item.anchor.bead_id, attempt.key)
            return Ok(Done(_still_running_text(state)))
        results.append(waited.value)
        # done_when commands leave build products (__pycache__, coverage files)
        # that would make land refuse the worktree as dirty.
        residue = gitops.is_clean(workdir.value)
        if isinstance(residue, Ok) and not residue.value:
            log.info("done_when left changes in %s; restoring %s", workdir.value, head.value)
        restored = gitops.reset_to(workdir.value, head.value)
        if isinstance(restored, Err):
            return restored
    summary = {r.name: ("pass" if r.passed else "fail") for r in results}
    log.info("checks for %s %s: %s", item.anchor.bead_id, attempt.key, summary)
    failed = [r for r in results if not r.passed]
    if failed:
        written = _write(layout.findings(attempt), _findings_text(attempt, results))
        if isinstance(written, Err):
            return written
        why = "failed checks: " + ", ".join(r.name for r in failed)
        retryable = report is None or report.status is not reports.Status.BLOCKED
        return _close_verify(ctx, item, scope.value, attempt, Verdict.REJECT, why, retryable)
    marked = ctx.gc.set_metadata(item.step.bead_id, {"lite.checks": "passed", "lite.checks_at": _now()})
    if isinstance(marked, Err):
        return marked
    ref = scope.value.ref
    split = (
        []
        if ref.total == 1
        else [f"This is {ref.label}: the diff holds only this card's work, and later cards do the rest."]
    )
    return Ok(
        Done(
            "\n".join(
                [
                    f"Every check passed for the {attempt.key} attempt on {item.anchor.bead_id}.",
                    *split,
                    f"Card: {layout.card}",
                    f"Diff: {layout.diff(attempt)}",
                    f"Executor report: {layout.report(attempt)}",
                    "",
                    "Review the diff against the card's Goal, Steps, Out of scope and Checklist.",
                    *_removed_tests_text(removed),
                    *_outside_files_text(outside),
                    "Approve when the change does what the card asks and nothing else:",
                    "  gc superpowers-lite verdict approve",
                    "Otherwise name each problem, with file and line:",
                    '  gc superpowers-lite verdict reject --reason "<problems>"',
                ]
            )
        )
    )


def _removed_tests_text(removed: tuple[str, ...]) -> list[str]:
    """The review instructions for an attempt that removes tests, or nothing when it removes none."""
    if not removed:
        return []
    return [
        "",
        "The attempt removes tests:",
        *(f"  - {line}" for line in removed),
        "Accept a removal only when the card asks for it, or when the diff deletes or replaces the",
        "code the removed test exercised. Otherwise reject, naming each test that must stay.",
        "",
    ]


def _outside_files_text(outside: tuple[str, ...]) -> list[str]:
    """The review instructions for an attempt that touches files the card does not list."""
    if not outside:
        return []
    return [
        "",
        "The attempt touches files the card does not list:",
        *(f"  - {path}" for path in outside),
        "The executor's report should say why it needed each one. Accept a file only when the",
        "change needs it to do what the card asks (a caller of a renamed method, a fixture, a",
        "regenerated baseline) and it does nothing the card's Out of scope rules out. Otherwise",
        "reject, naming each file that should not change.",
        "",
    ]


def verdict(ctx: Ctx, choice: Verdict, reason: str | None) -> Outcome:
    """Record the reviewer's verdict on an attempt whose checks passed."""
    if choice is Verdict.REJECT and not (reason or "").strip():
        return Err("a rejection needs --reason naming each problem")
    found = _claimed_step(ctx, "verify")
    if isinstance(found, Err):
        return found
    item = found.value
    attempt_result = step_attempt(item.step)
    if isinstance(attempt_result, Err):
        return attempt_result
    attempt = attempt_result.value
    if item.step.meta("lite.checks") != "passed":
        return Err("run `gc superpowers-lite verify` first; a verdict needs passing checks")
    scope = _card_scope(ctx, item)
    if isinstance(scope, Err):
        return scope
    layout = scope.value.files
    text = (reason or "approved").strip()
    review = _write(layout.attempt_dir(attempt) / "review.md", f"# {choice.value}\n\n{text}\n")
    if isinstance(review, Err):
        return review
    if choice is Verdict.REJECT:
        written = _write(layout.findings(attempt), _findings_text(attempt, [], text))
        if isinstance(written, Err):
            return written
    why = "review approved" if choice is Verdict.APPROVE else f"review: {text}"
    return _close_verify(ctx, item, scope.value, attempt, choice, why)


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
    # The item's steps share an abort_scope scope, and gc counts a member closed
    # without gc.outcome=pass as failed: the approval would abort the t3 attempt it opens.
    passed = gc.set_metadata(gates[0], {"gc.outcome": "pass"})
    if isinstance(passed, Err):
        return passed
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
