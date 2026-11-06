import json

import pytest

from litetools.ladder import Action, Tier, Verdict, decide


@pytest.mark.parametrize("tier", list(Tier))
def test_approval_always_lands(tier: Tier) -> None:
    decision = decide(tier, Verdict.APPROVE)
    assert decision.action is Action.LAND
    assert decision.outcome == "pass"
    assert json.loads(decision.output_json) == {"next": [{"action": "land"}]}


@pytest.mark.parametrize(("tier", "action"), [(Tier.T1, Action.T2), (Tier.T2, Action.T3)])
def test_rejection_escalates_one_tier(tier: Tier, action: Action) -> None:
    decision = decide(tier, Verdict.REJECT)
    assert decision.action is action
    assert decision.outcome == "pass"
    assert json.loads(decision.output_json) == {"next": [{"action": action.value}]}


def test_rejection_at_the_top_blocks_and_fails_with_no_next_step() -> None:
    decision = decide(Tier.T3, Verdict.REJECT)
    assert decision.action is Action.BLOCKED
    assert decision.outcome == "fail"
    assert json.loads(decision.output_json) == {"next": []}


def test_action_values_match_the_next_formula_conditions() -> None:
    assert {a.value for a in Action} == {"t2", "t3", "land", "blocked"}
    assert {t.value for t in Tier} == {"t1", "t2", "t3"}
