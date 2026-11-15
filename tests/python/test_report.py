import pytest

from litetools import report
from litetools.ladder import Blocker, Tier
from litetools.result import Err, Ok


@pytest.mark.parametrize("blocker", [Blocker.CARD, Blocker.WORK])
def test_a_blocked_report_keeps_its_blocker(blocker: Blocker) -> None:
    written = report.Report("st-1", Tier.T1, report.Status.BLOCKED, "", "the build needs a main class", blocker)
    assert report.parse(report.render(written)) == Ok(written)


def test_a_done_report_carries_no_blocker_line() -> None:
    written = report.Report("st-1", Tier.T2, report.Status.DONE, "abc123", "changed it")
    text = report.render(written)
    assert "blocker" not in text
    assert report.parse(text) == Ok(written)


def test_a_blocked_report_from_before_blocker_kinds_parses_without_one() -> None:
    legacy = '+++\nschema = "lite.report.v1"\ncard = "st-1"\ntier = "t1"\nstatus = "blocked"\ncommit = ""\n+++\n\n## Summary\n\nstuck\n'
    parsed = report.parse(legacy)
    assert isinstance(parsed, Ok) and parsed.value.blocker is None


@pytest.mark.parametrize(
    ("status", "blocker", "error"),
    [("blocked", "both", "the report blocker must be one of card, work"), ("done", "card", "only a blocked report names a blocker")],
)
def test_a_report_with_a_wrong_blocker_is_refused(status: str, blocker: str, error: str) -> None:
    text = (
        f'+++\nschema = "lite.report.v1"\ncard = "st-1"\ntier = "t1"\nstatus = "{status}"\ncommit = ""\n'
        f'blocker = "{blocker}"\n+++\n\n## Summary\n\nx\n'
    )
    assert report.parse(text) == Err(error)
