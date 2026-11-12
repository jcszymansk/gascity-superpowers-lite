"""The escalation ladder: which step follows a verified attempt.

::

    t1 ──reject──► t1 retry ──reject──► t2 ──reject──► (human gate) t3 ──reject──► blocked
     │   (blocked ─┼──────────────────► t2)
     └──approve────┴──approve───────────┴──approve─────────────────────┴──approve──┐
                                                                                    ▼
                                         another card left? ── yes ──► t1 on the next card
                                                             └─ no ───► land

An item whose bead was cut into several cards climbs the ladder once per card,
in card order; every card starts again at t1. Only the last card's approval
lands, so the target branch receives the item's cards together or not at all.

A rejected T1 attempt gets one retry on the same tier, which starts from the
rejected attempt and fixes what its findings name, because most T1 rejections
so far needed a small fix, not a stronger model. An attempt whose executor
reported a blocker skips the retry: the same model would stop at the same
place.

The verify step writes the decision as ``gc.output_json``; its
``on_complete`` bonds ``superpowers-lite-next`` once per entry of ``next``.
``blocked`` bonds nothing, and the verify step closes as failed so the item
fails with it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from litetools.result import Err, Ok, Result


class Tier(Enum):
    """Executor tiers, cheapest first."""

    T1 = "t1"
    T2 = "t2"
    T3 = "t3"


class Verdict(Enum):
    """The outcome of verifying one attempt."""

    APPROVE = "approve"
    REJECT = "reject"


class Action(Enum):
    """What runs after a verify step."""

    T1 = "t1"
    T2 = "t2"
    T3 = "t3"
    LAND = "land"
    BLOCKED = "blocked"


RETRIES = {Tier.T1: 1}
_ESCALATION = {Tier.T1: Action.T2, Tier.T2: Action.T3, Tier.T3: Action.BLOCKED}
_KEY = re.compile(r"(?P<tier>t[123])(?:\.(?P<round>[2-9]|[1-9][0-9]+))?")


@dataclass(frozen=True, slots=True)
class Attempt:
    """One executor attempt.

    Attributes:
        tier: The executor tier.
        round: 1 for the tier's first attempt, 2 for its retry.
    """

    tier: Tier
    round: int

    @property
    def key(self) -> str:
        """The attempt's name in metadata and artifact paths: ``t1``, ``t1.2``."""
        return self.tier.value if self.round == 1 else f"{self.tier.value}.{self.round}"


def highest(tiers: Iterable[Tier]) -> Result[Tier, str]:
    """Return the most expensive of ``tiers``: the tier an item of several cards passed at."""
    order = list(Tier)
    ranked = sorted(tiers, key=order.index)
    return Ok(ranked[-1]) if ranked else Err("no tiers to rank")


def first_attempt(tier: Tier) -> Attempt:
    """Return the first attempt at ``tier``."""
    return Attempt(tier, 1)


def parse_attempt(key: str) -> Result[Attempt, str]:
    """Parse an attempt key such as ``t1`` or ``t1.2``."""
    match = _KEY.fullmatch(key)
    if match is None:
        return Err(f"{key!r} is not an attempt key")
    return Ok(Attempt(Tier(match.group("tier")), int(match.group("round") or 1)))


def attempt_of(tier_value: str, round_value: str) -> Result[Attempt, str]:
    """Build an attempt from a step's ``lite.tier`` and ``lite.round`` metadata.

    An empty round means 1, for steps created before rounds existed.
    """
    tier = next((t for t in Tier if t.value == tier_value), None)
    if tier is None:
        return Err(f"no valid lite.tier (got {tier_value!r})")
    if not round_value:
        return Ok(first_attempt(tier))
    if not round_value.isdigit() or int(round_value) < 1:
        return Err(f"no valid lite.round (got {round_value!r})")
    rounds = int(round_value)
    if rounds > 1 + RETRIES.get(tier, 0):
        return Err(f"round {rounds} is past the {RETRIES.get(tier, 0)} retries {tier.value} allows")
    return Ok(Attempt(tier, rounds))


@dataclass(frozen=True, slots=True)
class Decision:
    """A verify step's result.

    Attributes:
        action: The next action.
        next_attempt: The attempt the next action runs, if it runs one.
        outcome: The ``gc.outcome`` the verify step closes with.
        output_json: The ``gc.output_json`` that drives ``on_complete``.
    """

    action: Action
    next_attempt: Attempt | None
    outcome: str
    output_json: str


def _next(action: Action, attempt: Attempt | None) -> Decision:
    rounds = str(attempt.round if attempt is not None else 1)
    return Decision(action, attempt, "pass", json.dumps({"next": [{"action": action.value, "round": rounds}]}))


def decide(attempt: Attempt, verdict: Verdict, retryable: bool, last_card: bool) -> Decision:
    """Return the decision for ``attempt`` after ``verdict``.

    Args:
        attempt: The attempt just verified.
        verdict: Approve or reject.
        retryable: False when the executor reported a blocker, which a retry
            by the same model would hit again.
        last_card: False when the item has cards after the one ``attempt``
            served, so an approval moves on to the next card instead of landing.
    """
    if verdict is Verdict.APPROVE:
        if not last_card:
            return _next(Action.T1, first_attempt(Tier.T1))
        return _next(Action.LAND, None)
    if retryable and attempt.round <= RETRIES.get(attempt.tier, 0):
        return _next(Action(attempt.tier.value), Attempt(attempt.tier, attempt.round + 1))
    action = _ESCALATION[attempt.tier]
    if action is Action.BLOCKED:
        return Decision(action, None, "fail", json.dumps({"next": []}))
    return _next(action, first_attempt(Tier(action.value)))
