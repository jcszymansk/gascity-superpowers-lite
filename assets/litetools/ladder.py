"""The escalation ladder: which step follows a verified attempt.

::

    t1 ──reject──► t2 ──reject──► (human gate) t3 ──reject──► blocked
     │              │                            │
     └──approve─────┴──approve───────────────────┴──approve──► land

The verify step writes the decision as ``gc.output_json``; its
``on_complete`` bonds ``superpowers-lite-next`` once per entry of ``next``.
``blocked`` bonds nothing, and the verify step closes as failed so the item
fails with it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum


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

    T2 = "t2"
    T3 = "t3"
    LAND = "land"
    BLOCKED = "blocked"


_ESCALATION = {Tier.T1: Action.T2, Tier.T2: Action.T3, Tier.T3: Action.BLOCKED}


@dataclass(frozen=True, slots=True)
class Decision:
    """A verify step's result.

    Attributes:
        action: The next action.
        outcome: The ``gc.outcome`` the verify step closes with.
        output_json: The ``gc.output_json`` that drives ``on_complete``.
    """

    action: Action
    outcome: str
    output_json: str


def decide(tier: Tier, verdict: Verdict) -> Decision:
    """Return the decision for an attempt at ``tier`` that got ``verdict``."""
    action = Action.LAND if verdict is Verdict.APPROVE else _ESCALATION[tier]
    if action is Action.BLOCKED:
        return Decision(action, "fail", json.dumps({"next": []}))
    return Decision(action, "pass", json.dumps({"next": [{"action": action.value}]}))
