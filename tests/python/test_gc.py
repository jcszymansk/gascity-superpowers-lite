"""Parsing ``gc bd show --json`` output into beads."""

from typing import Any

from litetools.gc import bead_from_json
from litetools.result import Err, Ok


def _bead(**extra: Any) -> dict[str, Any]:
    return {"id": "st-2", "status": "open", "title": "t", "metadata": {"target": "x"}, **extra}


def test_a_bead_without_dependencies_has_no_blockers() -> None:
    parsed = bead_from_json([_bead()])
    assert isinstance(parsed, Ok)
    assert parsed.value.blocked_by == ()
    assert parsed.value.meta("target") == "x"


def test_only_blocks_edges_become_blockers_with_their_status_and_metadata() -> None:
    deps = [
        {"id": "st-0", "dependency_type": "parent-child", "status": "open", "metadata": {}},
        {"id": "st-1", "dependency_type": "blocks", "status": "closed", "metadata": {"lite.result": "landed"}},
        {"id": "st-9", "dependency_type": "related", "status": "open"},
        {"id": "st-3", "dependency_type": "blocks", "status": "open", "dependencies": [{"id": "st-x"}]},
    ]
    parsed = bead_from_json(_bead(dependencies=deps))
    assert isinstance(parsed, Ok)
    blockers = parsed.value.blocked_by
    assert [b.bead_id for b in blockers] == ["st-1", "st-3"]
    assert blockers[0].status == "closed"
    assert blockers[0].meta("lite.result") == "landed"
    assert blockers[1].meta("lite.result") == ""
    assert blockers[1].blocked_by == ()


def test_malformed_dependencies_are_errors() -> None:
    assert isinstance(bead_from_json(_bead(dependencies={"id": "st-1"})), Err)
    broken = bead_from_json(_bead(dependencies=[{"dependency_type": "blocks", "status": "open"}]))
    assert isinstance(broken, Err)
    assert "malformed blocker" in broken.error
