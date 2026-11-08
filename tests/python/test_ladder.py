import json

import pytest

from litetools.ladder import Action, Attempt, RETRIES, Tier, Verdict, attempt_of, decide, first_attempt, parse_attempt
from litetools.result import Err, Ok


def next_of(output_json: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = json.loads(output_json)["next"]
    return entries


@pytest.mark.parametrize("attempt", [Attempt(Tier.T1, 1), Attempt(Tier.T1, 2), Attempt(Tier.T2, 1), Attempt(Tier.T3, 1)])
def test_approval_always_lands(attempt: Attempt) -> None:
    decision = decide(attempt, Verdict.APPROVE, retryable=True)
    assert decision.action is Action.LAND and decision.next_attempt is None
    assert decision.outcome == "pass"
    assert next_of(decision.output_json) == [{"action": "land", "round": "1"}]


def test_a_first_t1_rejection_retries_t1() -> None:
    decision = decide(first_attempt(Tier.T1), Verdict.REJECT, retryable=True)
    assert decision.action is Action.T1 and decision.next_attempt == Attempt(Tier.T1, 2)
    assert decision.outcome == "pass"
    assert next_of(decision.output_json) == [{"action": "t1", "round": "2"}]


def test_a_blocked_t1_attempt_skips_the_retry() -> None:
    decision = decide(first_attempt(Tier.T1), Verdict.REJECT, retryable=False)
    assert decision.action is Action.T2 and decision.next_attempt == first_attempt(Tier.T2)
    assert next_of(decision.output_json) == [{"action": "t2", "round": "1"}]


@pytest.mark.parametrize(
    ("attempt", "action"),
    [(Attempt(Tier.T1, 2), Action.T2), (first_attempt(Tier.T2), Action.T3)],
)
def test_rejection_without_retries_left_escalates_one_tier(attempt: Attempt, action: Action) -> None:
    decision = decide(attempt, Verdict.REJECT, retryable=True)
    assert decision.action is action
    assert decision.outcome == "pass"
    assert next_of(decision.output_json) == [{"action": action.value, "round": "1"}]


def test_rejection_at_the_top_blocks_and_fails_with_no_next_step() -> None:
    decision = decide(first_attempt(Tier.T3), Verdict.REJECT, retryable=True)
    assert decision.action is Action.BLOCKED and decision.next_attempt is None
    assert decision.outcome == "fail"
    assert next_of(decision.output_json) == []


def test_only_t1_retries() -> None:
    assert RETRIES == {Tier.T1: 1}


def test_action_values_match_the_next_formula_conditions() -> None:
    assert {a.value for a in Action} == {"t1", "t2", "t3", "land", "blocked"}
    assert {t.value for t in Tier} == {"t1", "t2", "t3"}


@pytest.mark.parametrize(("attempt", "key"), [(Attempt(Tier.T1, 1), "t1"), (Attempt(Tier.T1, 2), "t1.2"), (Attempt(Tier.T3, 1), "t3")])
def test_keys_round_trip(attempt: Attempt, key: str) -> None:
    assert attempt.key == key
    assert parse_attempt(key) == Ok(attempt)


@pytest.mark.parametrize("key", ["", "t4", "t1.1", "t1.0", "t1.", "T1", "t1.2x", "land"])
def test_bad_keys_are_refused(key: str) -> None:
    assert isinstance(parse_attempt(key), Err)


def test_step_metadata_gives_the_attempt() -> None:
    assert attempt_of("t1", "") == Ok(Attempt(Tier.T1, 1))
    assert attempt_of("t1", "2") == Ok(Attempt(Tier.T1, 2))
    assert attempt_of("t2", "1") == Ok(Attempt(Tier.T2, 1))


@pytest.mark.parametrize(("tier", "rounds"), [("t9", "1"), ("", ""), ("t1", "0"), ("t1", "x"), ("t1", "3"), ("t2", "2")])
def test_bad_step_metadata_is_refused(tier: str, rounds: str) -> None:
    assert isinstance(attempt_of(tier, rounds), Err)
