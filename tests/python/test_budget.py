"""Tests for resolving, recording and reading the ladder budget."""

from __future__ import annotations

import pytest

from litetools import budget
from litetools.budget import Kind, Limit, Setting, Source
from litetools.ladder import Tier, TierLimits
from litetools.result import Err, Ok

T1_ROUNDS = Setting(Tier.T1, Kind.ROUNDS)


def resolved(formula_vars: dict[str, str], environ: dict[str, str]) -> budget.Budget:
    result = budget.resolve(formula_vars, environ)
    assert isinstance(result, Ok), result
    return result.value


def test_every_setting_has_a_pack_default_that_reproduces_the_old_ladder() -> None:
    assert set(budget.PACK_DEFAULTS) == set(budget.SETTINGS)
    assert len(budget.SETTINGS) == 6
    plain = resolved({}, {})
    assert {s: plain.limits[s].value for s in budget.SETTINGS} == budget.PACK_DEFAULTS
    assert plain.limit(Tier.T1, Kind.ROUNDS) == Limit(2, Source.PACK)
    assert all(limit.source is Source.PACK for limit in plain.limits.values())


def test_setting_names() -> None:
    assert T1_ROUNDS.var_name == "lite_t1_rounds"
    assert T1_ROUNDS.env_name == "LITE_T1_ROUNDS"
    assert T1_ROUNDS.key == "lite.budget.t1.rounds"
    assert Setting(Tier.T3, Kind.ATTEMPTS).var_name == "lite_t3_attempts"


def test_a_formula_var_wins_over_the_city_env_which_wins_over_the_pack() -> None:
    result = resolved({"lite_t1_rounds": "5"}, {"LITE_T1_ROUNDS": "4", "LITE_T2_ATTEMPTS": "3"})
    assert result.limit(Tier.T1, Kind.ROUNDS) == Limit(5, Source.VAR)
    assert result.limit(Tier.T2, Kind.ATTEMPTS) == Limit(3, Source.ENV)
    assert result.limit(Tier.T3, Kind.ROUNDS) == Limit(1, Source.PACK)


@pytest.mark.parametrize("blank", ["", "  "])
def test_a_blank_value_counts_as_unset(blank: str) -> None:
    result = resolved({"lite_t1_rounds": blank}, {"LITE_T1_ROUNDS": "4"})
    assert result.limit(Tier.T1, Kind.ROUNDS) == Limit(4, Source.ENV)
    assert resolved({}, {"LITE_T1_ROUNDS": blank}).limit(Tier.T1, Kind.ROUNDS) == Limit(2, Source.PACK)


@pytest.mark.parametrize(("raw", "value"), [("1", 1), ("10", 10), (" 3 ", 3), ("03", 3)])
def test_whole_numbers_from_1_to_10_are_accepted(raw: str, value: int) -> None:
    assert resolved({"lite_t1_rounds": raw}, {}).limit(Tier.T1, Kind.ROUNDS) == Limit(value, Source.VAR)


@pytest.mark.parametrize("raw", ["0", "11", "30", "-1", "+3", "3.0", "three", "1e1", "٣"])
def test_other_values_are_refused_naming_the_setting_and_its_source(raw: str) -> None:
    from_var = budget.resolve({"lite_t1_rounds": raw}, {})
    assert isinstance(from_var, Err)
    assert from_var.error == [
        f"formula var lite_t1_rounds is {raw!r}; rounds must be a whole number from 1 to 10"
    ]
    from_env = budget.resolve({}, {"LITE_T2_ATTEMPTS": raw})
    assert isinstance(from_env, Err)
    assert from_env.error == [
        f"city env LITE_T2_ATTEMPTS is {raw!r}; attempts must be a whole number from 1 to 10"
    ]


def test_an_invalid_var_never_falls_back_to_a_valid_env() -> None:
    result = budget.resolve({"lite_t1_rounds": "0"}, {"LITE_T1_ROUNDS": "4"})
    assert isinstance(result, Err) and "formula var lite_t1_rounds" in result.error[0]


def test_every_invalid_setting_is_listed() -> None:
    result = budget.resolve({"lite_t1_rounds": "0", "lite_t3_attempts": "x"}, {"LITE_T2_ROUNDS": "99"})
    assert isinstance(result, Err) and len(result.error) == 3


def test_unrelated_vars_and_env_are_ignored() -> None:
    result = resolved({"lite_t4_rounds": "x", "issue": "st-1"}, {"LITE_VERIFY_WAIT_SECONDS": "5"})
    assert all(limit.source is Source.PACK for limit in result.limits.values())


def test_metadata_records_each_value_and_source() -> None:
    meta = resolved({"lite_t1_rounds": "3"}, {"LITE_T2_ATTEMPTS": "2"}).metadata()
    assert len(meta) == 12
    assert meta["lite.budget.t1.rounds"] == "3" and meta["lite.budget.t1.rounds.source"] == "var"
    assert meta["lite.budget.t2.attempts"] == "2" and meta["lite.budget.t2.attempts.source"] == "env"
    assert meta["lite.budget.t3.rounds"] == "1" and meta["lite.budget.t3.rounds.source"] == "pack"


def test_recorded_reads_back_what_metadata_wrote() -> None:
    original = resolved({"lite_t1_rounds": "3", "lite_t3_attempts": "10"}, {"LITE_T2_ATTEMPTS": "2"})
    assert budget.recorded({**original.metadata(), "lite.kind": "bugfix"}) == Ok(original)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("lite.budget.t2.rounds", None, "has no lite.budget.t2.rounds"),
        ("lite.budget.t2.rounds", " ", "has no lite.budget.t2.rounds"),
        ("lite.budget.t2.rounds", "0", "lite.budget.t2.rounds is '0'"),
        ("lite.budget.t2.rounds.source", "rig", "lite.budget.t2.rounds.source is 'rig'"),
        ("lite.budget.t2.rounds.source", None, "lite.budget.t2.rounds.source is ''"),
    ],
)
def test_recorded_refuses_a_missing_or_invalid_record(key: str, value: str | None, message: str) -> None:
    meta = resolved({}, {}).metadata()
    if value is None:
        del meta[key]
    else:
        meta[key] = value
    result = budget.recorded(meta)
    assert isinstance(result, Err) and message in result.error


def test_summary_names_every_tier_with_its_sources() -> None:
    summary = resolved({"lite_t1_rounds": "3"}, {"LITE_T2_ATTEMPTS": "2"}).summary()
    assert summary == "t1 1x3 (pack, var), t2 2x1 (env, pack), t3 1x1 (pack, pack)"


def test_tier_limits_give_the_ladder_each_tiers_attempts_and_rounds() -> None:
    result = resolved({"lite_t2_attempts": "3", "lite_t2_rounds": "4"}, {})
    assert result.tier_limits(Tier.T2) == TierLimits(3, 4)
    assert result.tier_limits(Tier.T1) == TierLimits(1, 2)
