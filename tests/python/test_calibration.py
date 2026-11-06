"""The calibration cards stay valid lite cards with a complete, consistent source record."""

import re
import tomllib
from pathlib import Path

import pytest

from litetools import card
from litetools.result import Ok

CALIBRATION = Path(__file__).resolve().parents[2] / "calibration"
CARD_DIRS = sorted(path.parent for path in CALIBRATION.glob("*/*/card.md"))
SHA = re.compile(r"[0-9a-f]{40}")


def test_there_are_calibration_cards() -> None:
    assert len(CARD_DIRS) >= 4


@pytest.mark.parametrize("card_dir", CARD_DIRS, ids=lambda d: f"{d.parent.name}/{d.name}")
def test_card_parses_and_matches_its_source(card_dir: Path) -> None:
    parsed = card.parse((card_dir / "card.md").read_text(encoding="utf-8"), require_checklist=False)
    assert isinstance(parsed, Ok), parsed
    source = tomllib.loads((card_dir / "source.toml").read_text(encoding="utf-8"))
    assert set(source) == {"rig", "base", "solution", "subject", "notes", "tests"}
    assert source["rig"] == card_dir.parent.name
    assert SHA.fullmatch(source["base"]) and SHA.fullmatch(source["solution"])
    assert source["base"] != source["solution"]
    assert parsed.value.card_id == f"cal-st-{card_dir.name}"
    assert source["tests"] and set(source["tests"]) <= set(parsed.value.files)
