"""The escalation ladder: which step follows a verified attempt.

Each tier has a budget of attempts and rounds (see ``budget``). An attempt
starts from the card's base; a round is one executor session within it, and
every round after the first continues from the previous round's commit::

    approve ──────────────────────► next card at t1, or land after the last card
    correct ─ rounds left ────────► next round of this attempt
            └ last round ─┐
    restart ─ attempts left ──────► next attempt at this tier, from the card's base
            └ last attempt ───────► escalate: t1 ► t2 ► (human gate) t3 ► blocked
    executor blocker ─────────────► escalate at once

An item whose bead was cut into several cards climbs the ladder once per card,
in card order; every card starts again at t1. Only the last card's approval
lands, so the target branch receives the item's cards together or not at all.

A blocker skips the tier's remaining rounds and attempts, because the same
model would stop at the same place. The human gate opens once, when a card
first escalates into t3, not again for later t3 attempts or rounds.

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
    CORRECT = "correct"
    RESTART = "restart"


class Action(Enum):
    """What runs after a verify step."""

    T1 = "t1"
    T2 = "t2"
    T3 = "t3"
    LAND = "land"
    BLOCKED = "blocked"


_ESCALATION = {Tier.T1: Action.T2, Tier.T2: Action.T3, Tier.T3: Action.BLOCKED}
_COUNT = r"(?:[2-9]|[1-9][0-9]+)"
_KEY = re.compile(rf"(?P<tier>t[123])(?:\.a(?P<number>{_COUNT}))?(?:\.r(?P<round>{_COUNT}))?")


@dataclass(frozen=True, slots=True)
class Attempt:
    """One executor session on a card.

    Attributes:
        tier: The executor tier.
        number: Which attempt at the tier, from 1; each starts from the card's base.
        round: Which round of the attempt, from 1; each later round continues the previous one.
    """

    tier: Tier
    number: int
    round: int

    @property
    def key(self) -> str:
        """The attempt's name in metadata and artifact paths: ``t1``, ``t1.r2``, ``t1.a2.r3``.

        Parts equal to 1 are left out, so a tier's first session is plainly ``t1``.
        """
        number = f".a{self.number}" if self.number > 1 else ""
        rounds = f".r{self.round}" if self.round > 1 else ""
        return f"{self.tier.value}{number}{rounds}"

    def earlier_rounds(self) -> tuple["Attempt", ...]:
        """Return this attempt's rounds up to and including this one, first round first."""
        return tuple(Attempt(self.tier, self.number, r) for r in range(1, self.round + 1))


@dataclass(frozen=True, slots=True)
class TierLimits:
    """How many attempts, and rounds per attempt, one tier gets.

    Attributes:
        attempts: The number of attempts, at least 1.
        rounds: The number of rounds per attempt, at least 1.
    """

    attempts: int
    rounds: int

    def allows(self, attempt: Attempt) -> bool:
        """Return True when ``attempt`` lies within these limits."""
        return attempt.number <= self.attempts and attempt.round <= self.rounds


def highest(tiers: Iterable[Tier]) -> Result[Tier, str]:
    """Return the most expensive of ``tiers``: the tier an item of several cards passed at."""
    order = list(Tier)
    ranked = sorted(tiers, key=order.index)
    return Ok(ranked[-1]) if ranked else Err("no tiers to rank")


def first_attempt(tier: Tier) -> Attempt:
    """Return the first round of the first attempt at ``tier``."""
    return Attempt(tier, 1, 1)


def parse_attempt(key: str) -> Result[Attempt, str]:
    """Parse an attempt key such as ``t1``, ``t1.r2`` or ``t2.a2.r3``."""
    match = _KEY.fullmatch(key)
    if match is None:
        return Err(f"{key!r} is not an attempt key")
    return Ok(Attempt(Tier(match.group("tier")), int(match.group("number") or 1), int(match.group("round") or 1)))


def _count(raw: str, name: str) -> Result[int, str]:
    if not raw:
        return Ok(1)
    if not raw.isascii() or not raw.isdigit() or int(raw) < 1:
        return Err(f"no valid {name} (got {raw!r})")
    return Ok(int(raw))


def attempt_of(tier_value: str, number_value: str, round_value: str) -> Result[Attempt, str]:
    """Build an attempt from a step's ``lite.tier``, ``lite.attempt_number`` and ``lite.round``.

    An empty number or round means 1. Whether the attempt fits the item's
    budget is checked where the budget is known.
    """
    tier = next((t for t in Tier if t.value == tier_value), None)
    if tier is None:
        return Err(f"no valid lite.tier (got {tier_value!r})")
    number = _count(number_value, "lite.attempt_number")
    if isinstance(number, Err):
        return number
    rounds = _count(round_value, "lite.round")
    if isinstance(rounds, Err):
        return rounds
    return Ok(Attempt(tier, number.value, rounds.value))


@dataclass(frozen=True, slots=True)
class Decision:
    """A verify step's result.

    Attributes:
        action: The next action.
        next_attempt: The attempt the next action runs, if it runs one.
        gate: True when the next attempt waits for a human first.
        outcome: The ``gc.outcome`` the verify step closes with.
        output_json: The ``gc.output_json`` that drives ``on_complete``.
    """

    action: Action
    next_attempt: Attempt | None
    gate: bool
    outcome: str
    output_json: str


def _next(action: Action, attempt: Attempt | None, gate: bool = False) -> Decision:
    entry = {
        "action": action.value,
        "attempt": str(attempt.number if attempt is not None else 1),
        "round": str(attempt.round if attempt is not None else 1),
        "gate": "yes" if gate else "no",
    }
    return Decision(action, attempt, gate, "pass", json.dumps({"next": [entry]}))


def _escalate(tier: Tier) -> Decision:
    action = _ESCALATION[tier]
    if action is Action.BLOCKED:
        return Decision(action, None, False, "fail", json.dumps({"next": []}))
    return _next(action, first_attempt(Tier(action.value)), gate=action is Action.T3)


def decide(attempt: Attempt, verdict: Verdict, blocked: bool, last_card: bool, limits: TierLimits) -> Decision:
    """Return the decision for ``attempt`` after ``verdict``.

    Args:
        attempt: The attempt just verified.
        verdict: Approve, correct or restart.
        blocked: True when the executor reported a blocker, which another
            session of the same model would hit again.
        last_card: False when the item has cards after the one ``attempt``
            served, so an approval moves on to the next card instead of landing.
        limits: The budget of ``attempt``'s tier.
    """
    if verdict is Verdict.APPROVE:
        return _next(Action.LAND, None) if last_card else _next(Action.T1, first_attempt(Tier.T1))
    if blocked:
        return _escalate(attempt.tier)
    action = Action(attempt.tier.value)
    if verdict is Verdict.CORRECT and attempt.round < limits.rounds:
        return _next(action, Attempt(attempt.tier, attempt.number, attempt.round + 1))
    if attempt.number < limits.attempts:
        return _next(action, Attempt(attempt.tier, attempt.number + 1, 1))
    return _escalate(attempt.tier)
