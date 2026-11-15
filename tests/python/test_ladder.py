import json

import pytest

from litetools.ladder import (
    Action,
    Attempt,
    Blocker,
    Tier,
    TierLimits,
    Verdict,
    attempt_of,
    decide,
    first_attempt,
    highest,
    parse_attempt,
)
from litetools.result import Err, Ok

ONE = TierLimits(1, 1)
WIDE = TierLimits(3, 3)


def next_of(output_json: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = json.loads(output_json)["next"]
    return entries


def entry(action: str, attempt: int = 1, round_: int = 1, gate: str = "no") -> dict[str, str]:
    return {"action": action, "attempt": str(attempt), "round": str(round_), "gate": gate}


ATTEMPTS = [Attempt(Tier.T1, 1, 1), Attempt(Tier.T1, 2, 3), Attempt(Tier.T2, 1, 1), Attempt(Tier.T3, 3, 2)]


@pytest.mark.parametrize("attempt", ATTEMPTS)
@pytest.mark.parametrize("blocker", [None, Blocker.WORK, Blocker.CARD])
def test_approval_of_the_last_card_lands(attempt: Attempt, blocker: Blocker | None) -> None:
    decision = decide(attempt, Verdict.APPROVE, blocker, last_card=True, limits=ONE)
    assert decision.action is Action.LAND and decision.next_attempt is None and not decision.gate
    assert decision.outcome == "pass"
    assert next_of(decision.output_json) == [entry("land")]


@pytest.mark.parametrize("attempt", ATTEMPTS)
def test_approval_with_cards_left_starts_the_next_card_at_t1(attempt: Attempt) -> None:
    decision = decide(attempt, Verdict.APPROVE, None, last_card=False, limits=WIDE)
    assert decision.action is Action.T1 and decision.next_attempt == first_attempt(Tier.T1)
    assert next_of(decision.output_json) == [entry("t1")]


@pytest.mark.parametrize("last_card", [True, False])
@pytest.mark.parametrize("verdict", [Verdict.CORRECT, Verdict.RESTART])
def test_a_verdict_other_than_approve_ignores_the_cards_left(last_card: bool, verdict: Verdict) -> None:
    decision = decide(first_attempt(Tier.T1), verdict, None, last_card, WIDE)
    assert decision.action is Action.T1


def test_correct_with_rounds_left_runs_the_next_round_of_the_same_attempt() -> None:
    decision = decide(Attempt(Tier.T2, 2, 1), Verdict.CORRECT, None, True, WIDE)
    assert decision.action is Action.T2 and decision.next_attempt == Attempt(Tier.T2, 2, 2)
    assert decision.outcome == "pass"
    assert next_of(decision.output_json) == [entry("t2", 2, 2)]


def test_correct_in_the_last_round_starts_the_next_attempt() -> None:
    decision = decide(Attempt(Tier.T1, 1, 3), Verdict.CORRECT, None, True, WIDE)
    assert decision.next_attempt == Attempt(Tier.T1, 2, 1)
    assert next_of(decision.output_json) == [entry("t1", 2, 1)]


def test_restart_skips_the_rounds_left_and_starts_the_next_attempt() -> None:
    decision = decide(Attempt(Tier.T1, 1, 1), Verdict.RESTART, None, True, WIDE)
    assert decision.next_attempt == Attempt(Tier.T1, 2, 1)


@pytest.mark.parametrize("verdict", [Verdict.CORRECT, Verdict.RESTART])
def test_the_last_round_of_the_last_attempt_escalates_from_t1_to_t2(verdict: Verdict) -> None:
    decision = decide(Attempt(Tier.T1, 3, 3), verdict, None, True, WIDE)
    assert decision.action is Action.T2 and decision.next_attempt == first_attempt(Tier.T2)
    assert not decision.gate
    assert next_of(decision.output_json) == [entry("t2")]


def test_restart_in_the_last_attempt_escalates_even_with_rounds_left() -> None:
    decision = decide(Attempt(Tier.T1, 3, 1), Verdict.RESTART, None, True, WIDE)
    assert decision.action is Action.T2


def test_escalating_into_t3_opens_the_human_gate() -> None:
    decision = decide(Attempt(Tier.T2, 1, 1), Verdict.RESTART, None, True, ONE)
    assert decision.action is Action.T3 and decision.next_attempt == first_attempt(Tier.T3)
    assert decision.gate
    assert next_of(decision.output_json) == [entry("t3", gate="yes")]


@pytest.mark.parametrize(
    ("verdict", "following"), [(Verdict.CORRECT, Attempt(Tier.T3, 1, 2)), (Verdict.RESTART, Attempt(Tier.T3, 2, 1))]
)
def test_later_t3_sessions_need_no_second_approval(verdict: Verdict, following: Attempt) -> None:
    decision = decide(first_attempt(Tier.T3), verdict, None, True, WIDE)
    assert decision.next_attempt == following and not decision.gate
    assert next_of(decision.output_json)[0]["gate"] == "no"


@pytest.mark.parametrize("verdict", [Verdict.CORRECT, Verdict.RESTART])
def test_the_end_of_the_t3_budget_blocks_and_fails_with_no_next_step(verdict: Verdict) -> None:
    decision = decide(Attempt(Tier.T3, 1, 1), verdict, None, True, ONE)
    assert decision.action is Action.BLOCKED and decision.next_attempt is None and not decision.gate
    assert decision.outcome == "fail"
    assert next_of(decision.output_json) == []


@pytest.mark.parametrize(
    ("tier", "action"), [(Tier.T1, Action.T2), (Tier.T2, Action.T3), (Tier.T3, Action.BLOCKED)]
)
@pytest.mark.parametrize("verdict", [Verdict.CORRECT, Verdict.RESTART])
def test_a_blocker_escalates_at_once_whatever_the_budget_leaves(tier: Tier, action: Action, verdict: Verdict) -> None:
    decision = decide(first_attempt(tier), verdict, Blocker.WORK, True, WIDE)
    assert decision.action is action


@pytest.mark.parametrize("attempt", [first_attempt(Tier.T1), Attempt(Tier.T1, 1, 2), first_attempt(Tier.T2)])
@pytest.mark.parametrize("verdict", [Verdict.CORRECT, Verdict.RESTART])
@pytest.mark.parametrize("last_card", [False, True])
def test_a_card_blocker_blocks_at_once_without_a_higher_tier_or_the_gate(
    attempt: Attempt, verdict: Verdict, last_card: bool
) -> None:
    decision = decide(attempt, verdict, Blocker.CARD, last_card, WIDE)
    assert decision.action is Action.BLOCKED and decision.next_attempt is None and not decision.gate
    assert decision.outcome == "fail"
    assert next_of(decision.output_json) == []


def test_tier_limits_allow_only_attempts_inside_them() -> None:
    limits = TierLimits(2, 3)
    assert limits.allows(Attempt(Tier.T1, 2, 3))
    assert not limits.allows(Attempt(Tier.T1, 3, 1))
    assert not limits.allows(Attempt(Tier.T1, 1, 4))


def test_action_values_match_the_next_formula_conditions() -> None:
    assert {a.value for a in Action} == {"t1", "t2", "t3", "land", "blocked"}
    assert {t.value for t in Tier} == {"t1", "t2", "t3"}
    assert {v.value for v in Verdict} == {"approve", "correct", "restart"}


@pytest.mark.parametrize(
    ("attempt", "key"),
    [
        (Attempt(Tier.T1, 1, 1), "t1"),
        (Attempt(Tier.T1, 1, 2), "t1.r2"),
        (Attempt(Tier.T2, 2, 1), "t2.a2"),
        (Attempt(Tier.T3, 10, 12), "t3.a10.r12"),
    ],
)
def test_keys_round_trip(attempt: Attempt, key: str) -> None:
    assert attempt.key == key
    assert parse_attempt(key) == Ok(attempt)


@pytest.mark.parametrize(
    "key", ["", "t4", "t1.2", "t1.r1", "t1.a1", "t1.r0", "t1.r2.a2", "t1.", "T1", "t1.r2x", "t1.a01", "land"]
)
def test_bad_keys_are_refused(key: str) -> None:
    assert isinstance(parse_attempt(key), Err)


def test_earlier_rounds_lists_the_attempt_from_its_first_round() -> None:
    assert Attempt(Tier.T2, 2, 3).earlier_rounds() == (Attempt(Tier.T2, 2, 1), Attempt(Tier.T2, 2, 2), Attempt(Tier.T2, 2, 3))
    assert first_attempt(Tier.T1).earlier_rounds() == (first_attempt(Tier.T1),)


def test_step_metadata_gives_the_attempt() -> None:
    assert attempt_of("t1", "", "") == Ok(Attempt(Tier.T1, 1, 1))
    assert attempt_of("t1", "1", "2") == Ok(Attempt(Tier.T1, 1, 2))
    assert attempt_of("t2", "3", "") == Ok(Attempt(Tier.T2, 3, 1))
    assert attempt_of("t3", "12", "11") == Ok(Attempt(Tier.T3, 12, 11))


@pytest.mark.parametrize(
    ("tier", "number", "rounds"),
    [("t9", "1", "1"), ("", "", ""), ("t1", "0", "1"), ("t1", "1", "0"), ("t1", "x", ""), ("t1", "", "-1"), ("t1", "٢", "")],
)
def test_bad_step_metadata_is_refused(tier: str, number: str, rounds: str) -> None:
    assert isinstance(attempt_of(tier, number, rounds), Err)


@pytest.mark.parametrize(
    ("tiers", "top"),
    [([Tier.T1], Tier.T1), ([Tier.T2, Tier.T1], Tier.T2), ([Tier.T1, Tier.T3, Tier.T2], Tier.T3)],
)
def test_highest_ranks_tiers_by_cost(tiers: list[Tier], top: Tier) -> None:
    assert highest(tiers) == Ok(top)


def test_highest_of_nothing_is_an_error() -> None:
    assert isinstance(highest([]), Err)
