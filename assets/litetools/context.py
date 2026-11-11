"""Where a pack command runs: its environment, its claim and its work item.

A step bead leads to its item like this::

    step ──gc.root_bead_id──► item root ──gc.input_convoy_id──► convoy
                                  │                               │
                         lite.anchor_id (cache)   drain-unit? gc.drain_member_id
                                  └──────────────► source anchor ◄┘

The source anchor is the work bead the item serves. Lite keeps its per-item
state there (``work_dir``, ``target``, ``lite.*``), never on a convoy or root.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from litetools.gc import Bead, Gc
from litetools.ladder import Attempt, attempt_of
from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

DRAIN_UNIT_KIND = "drain-unit-convoy"
DEFAULT_VERIFY_WAIT_SECONDS = 100.0
"""Under the two minutes an agent shell tool waits by default, so verify always
returns in the foreground, whatever timeout the agent picks."""


@dataclass(frozen=True, slots=True)
class Env:
    """The agent environment a command needs.

    Attributes:
        city: ``GC_CITY``.
        rig: ``GC_RIG``.
        rig_root: ``GC_RIG_ROOT``.
        session: The session identity claims are stored under.
        identities: Every name the claim hook may record as our assignee.
        route: ``GC_TEMPLATE``, the route our claims must carry, or empty.
        pack_dir: ``GC_PACK_DIR``.
        verify_wait_seconds: How long one ``verify`` waits for ``done_when``
            (``LITE_VERIFY_WAIT_SECONDS``, default 100).
    """

    city: Path
    rig: str
    rig_root: Path
    session: str
    identities: frozenset[str]
    route: str
    pack_dir: Path
    verify_wait_seconds: float = DEFAULT_VERIFY_WAIT_SECONDS


def load_env(environ: Mapping[str, str]) -> Result[Env, str]:
    """Read the agent environment; fail if a required variable is empty."""
    required = ("GC_CITY", "GC_RIG", "GC_RIG_ROOT", "GC_PACK_DIR")
    missing = [name for name in required if not environ.get(name, "").strip()]
    session = next(
        (environ[n] for n in ("GC_SESSION_ID", "GC_SESSION_NAME", "GC_AGENT") if environ.get(n, "").strip()), ""
    )
    if not session:
        missing.append("GC_SESSION_ID")
    if missing:
        return Err(f"missing environment: {', '.join(missing)}")
    raw_wait = environ.get("LITE_VERIFY_WAIT_SECONDS", "").strip()
    try:
        verify_wait = float(raw_wait) if raw_wait else DEFAULT_VERIFY_WAIT_SECONDS
    except ValueError:
        return Err(f"LITE_VERIFY_WAIT_SECONDS is not a number: {raw_wait!r}")
    if verify_wait < 0:
        return Err(f"LITE_VERIFY_WAIT_SECONDS is negative: {raw_wait!r}")
    identities = frozenset(
        environ[n].strip()
        for n in ("BEADS_ACTOR", "GC_ALIAS", "GC_SESSION_ID", "GC_SESSION_NAME", "GC_AGENT")
        if environ.get(n, "").strip()
    )
    return Ok(
        Env(
            city=Path(environ["GC_CITY"]),
            rig=environ["GC_RIG"].strip(),
            rig_root=Path(environ["GC_RIG_ROOT"]),
            session=session.strip(),
            identities=identities,
            route=environ.get("GC_TEMPLATE", "").strip(),
            pack_dir=Path(environ["GC_PACK_DIR"]),
            verify_wait_seconds=verify_wait,
        )
    )


def claim_file(env: Env) -> Path:
    """Return the file that records this session's current claim."""
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in env.session)
    return env.city / ".gc" / "runtime" / "superpowers-lite" / "claims" / f"{safe}.json"


def save_claim(env: Env, bead_id: str) -> Result[None, str]:
    """Record ``bead_id`` as this session's claim."""
    path = claim_file(env)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"bead_id": bead_id}) + "\n", encoding="utf-8")
    except OSError as error:
        return Err(f"could not record the claim in {path}: {error}")
    return Ok(None)


def forget_claim(env: Env) -> None:
    """Drop this session's claim record, if any."""
    claim_file(env).unlink(missing_ok=True)


def claimed_bead_id(env: Env) -> Result[str, str]:
    """Return this session's claimed bead id, or why there is none."""
    path = claim_file(env)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Err("no claimed bead: run `gc superpowers-lite claim` first")
    except (OSError, json.JSONDecodeError) as error:
        return Err(f"unreadable claim record {path}: {error}")
    bead_id = data.get("bead_id") if isinstance(data, dict) else None
    if not isinstance(bead_id, str) or not bead_id.strip():
        return Err(f"claim record {path} has no bead id")
    return Ok(bead_id.strip())


@dataclass(frozen=True, slots=True)
class Layout:
    """The item's artifact files, outside every repository.

    Attributes:
        root: ``<city>/.gc/artifacts/<rig>/superpowers-lite/<anchor id>``.
    """

    root: Path

    @property
    def card_draft(self) -> Path:
        """The card as the cutter writes it."""
        return self.root / "card.draft.md"

    @property
    def card(self) -> Path:
        """The sealed card executors work from."""
        return self.root / "card.md"

    def attempt_dir(self, attempt: Attempt) -> Path:
        """The directory for one attempt."""
        return self.root / "attempts" / attempt.key

    def report(self, attempt: Attempt) -> Path:
        """The executor's report for ``attempt``."""
        return self.attempt_dir(attempt) / "report.md"

    def diff(self, attempt: Attempt) -> Path:
        """The attempt's full diff, saved for the reviewer and the next attempt."""
        return self.attempt_dir(attempt) / "attempt.diff"

    def findings(self, attempt: Attempt) -> Path:
        """Why ``attempt`` was rejected, for the next attempt."""
        return self.attempt_dir(attempt) / "findings.md"


def layout_for(env: Env, anchor_id: str) -> Layout:
    """Return the artifact layout of the item serving ``anchor_id``."""
    return Layout(env.city / ".gc" / "artifacts" / env.rig / "superpowers-lite" / anchor_id)


@dataclass(frozen=True, slots=True)
class Item:
    """A claimed step and the work item it belongs to.

    Attributes:
        step: The claimed step bead.
        root: The item's workflow root.
        anchor: The source anchor (the work bead).
        parent_convoy_id: The convoy the anchor was drained from, or empty.
    """

    step: Bead
    root: Bead
    anchor: Bead
    parent_convoy_id: str


def resolve_item(gc: Gc, step: Bead) -> Result[Item, str]:
    """Resolve the item a step bead belongs to."""
    root_id = step.meta("gc.root_bead_id")
    if not root_id:
        return Err(f"step {step.bead_id} has no gc.root_bead_id")
    root = gc.show(root_id)
    if isinstance(root, Err):
        return root
    convoy_id = root.value.meta("gc.input_convoy_id")
    if not convoy_id:
        return Err(f"item root {root_id} has no gc.input_convoy_id")
    convoy = gc.show(convoy_id)
    if isinstance(convoy, Err):
        return convoy
    if convoy.value.meta("gc.synthetic_kind") == DRAIN_UNIT_KIND:
        anchor_id = convoy.value.meta("gc.drain_member_id")
        parent = convoy.value.meta("gc.parent_convoy_id")
    else:
        anchor_id, parent = convoy_id, ""
    if not anchor_id:
        return Err(f"drain-unit convoy {convoy_id} has no gc.drain_member_id")
    cached = root.value.meta("lite.anchor_id")
    if cached and cached != anchor_id:
        return Err(f"item root {root_id} names anchor {cached}, but its convoy names {anchor_id}")
    if anchor_id == convoy_id and convoy.value.meta("gc.synthetic_kind"):
        return Err(f"source anchor {anchor_id} is a synthetic convoy")
    anchor = gc.show(anchor_id)
    if isinstance(anchor, Err):
        return anchor
    log.info("step %s belongs to item %s, anchor %s", step.bead_id, root_id, anchor_id)
    return Ok(Item(step, root.value, anchor.value, parent))


def step_attempt(step: Bead) -> Result[Attempt, str]:
    """Return the attempt an attempt or verify step serves, from ``lite.tier`` and ``lite.round``."""
    found = attempt_of(step.meta("lite.tier"), step.meta("lite.round"))
    return Err(f"step {step.bead_id} has {found.error}") if isinstance(found, Err) else found
