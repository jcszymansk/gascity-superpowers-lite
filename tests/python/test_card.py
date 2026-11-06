from pathlib import Path

import pytest

from litetools import card
from litetools.card import Kind, Section
from litetools.result import Err, Ok

PACK = Path(__file__).resolve().parents[2]

FRONT = """+++
schema = "lite.card.v1"
id = "smt-12"
kind = "bugfix"
files = ["src/parse.rs", "tests/parse.rs"]
done_when = ["cargo test --test parse"]
+++
"""

BODY = """
## Goal

Parsing an empty header returns an error instead of panicking.

## Interfaces

None.

## Context

src/parse.rs:40-52 unwraps the first header line.

## Steps

1. Add a test.
2. Return ParseError::Empty.

## Out of scope

The lexer.
"""


def cutter_card(front: str = FRONT, body: str = BODY) -> str:
    return front + body


def errors_of(result: object) -> list[str]:
    assert isinstance(result, Err), result
    assert isinstance(result.error, list)
    return result.error


def test_valid_card_parses_with_every_field() -> None:
    result = card.parse(cutter_card(), require_checklist=False)
    assert isinstance(result, Ok)
    parsed = result.value
    assert parsed.card_id == "smt-12"
    assert parsed.kind is Kind.BUGFIX
    assert parsed.files == ("src/parse.rs", "tests/parse.rs")
    assert parsed.done_when == ("cargo test --test parse",)
    assert parsed.section(Section.GOAL).startswith("Parsing an empty header")
    assert parsed.section(Section.CHECKLIST) == ""


@pytest.mark.parametrize("section", [s for s in card.CUTTER_SECTIONS])
def test_every_cutter_section_is_required(section: Section) -> None:
    body = BODY.replace(f"## {section.value}\n", "## Removed\n")
    errors = errors_of(card.parse(cutter_card(body=body), require_checklist=False))
    assert f"missing section '## {section.value}'" in errors
    assert "unknown section '## Removed'" in errors


def test_empty_section_is_rejected() -> None:
    body = BODY.replace("The lexer.", "")
    assert "section '## Out of scope' is empty" in errors_of(
        card.parse(cutter_card(body=body), require_checklist=False)
    )


def test_duplicate_section_is_rejected() -> None:
    body = BODY + "\n## Goal\n\nagain\n"
    assert "section '## Goal' appears twice" in errors_of(
        card.parse(cutter_card(body=body), require_checklist=False)
    )


def test_text_before_first_section_is_rejected() -> None:
    errors = errors_of(card.parse(cutter_card(body="stray\n" + BODY), require_checklist=False))
    assert "text before the first '## ' section" in errors


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no fence\n", "the card must start with a '+++' line"),
        ("+++\nid = 'x'\n", "the front matter has no closing '+++' line"),
        ("+++\nid = \n+++\n", "the front matter is not valid TOML"),
    ],
)
def test_broken_front_matter(text: str, message: str) -> None:
    errors = errors_of(card.parse(text, require_checklist=False))
    assert any(error.startswith(message) for error in errors), errors


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('schema = "lite.card.v1"', 'schema = "lite.card.v0"', "'schema' must be \"lite.card.v1\""),
        ('id = "smt-12"', 'id = " "', "'id' must name the work bead"),
        ('kind = "bugfix"', 'kind = "refactor"', "'kind' must be one of bugfix, tdd-feature"),
        ('files = ["src/parse.rs", "tests/parse.rs"]', "files = []", "'files' must be a non-empty list of strings"),
        ('files = ["src/parse.rs", "tests/parse.rs"]', 'files = "src/parse.rs"', "'files' must be a non-empty list of strings"),
        ('files = ["src/parse.rs", "tests/parse.rs"]', 'files = ["a", "a"]', "'files' lists an entry twice"),
        ('files = ["src/parse.rs", "tests/parse.rs"]', 'files = ["a", 3]', "every entry of 'files' must be a non-empty string"),
        ('done_when = ["cargo test --test parse"]', "done_when = []", "'done_when' must be a non-empty list of strings"),
        ('done_when = ["cargo test --test parse"]', 'done_when = ["x"]\nextra = 1', "unknown front matter key 'extra'"),
    ],
)
def test_front_matter_rules(old: str, new: str, message: str) -> None:
    assert old in FRONT
    errors = errors_of(card.parse(cutter_card(front=FRONT.replace(old, new)), require_checklist=False))
    assert message in errors, errors


@pytest.mark.parametrize("path", ["/etc/passwd", "../x", "a/../../x", "a\\b", " a", ""])
def test_file_paths_must_stay_inside_the_repository(path: str) -> None:
    front = FRONT.replace('["src/parse.rs", "tests/parse.rs"]', f"[{path!r}]".replace("'", '"'))
    errors = errors_of(card.parse(cutter_card(front=front), require_checklist=False))
    assert any("file path" in error or "non-empty string" in error for error in errors), errors


def test_size_caps() -> None:
    many = ", ".join(f'"f{i}"' for i in range(card.MAX_FILES + 1))
    front = FRONT.replace('["src/parse.rs", "tests/parse.rs"]', f"[{many}]")
    assert any("the cap is 8" in e for e in errors_of(card.parse(cutter_card(front=front), require_checklist=False)))
    huge = cutter_card(body=BODY + "x" * card.MAX_CARD_BYTES)
    assert errors_of(card.parse(huge, require_checklist=False)) == [
        f"the card is over {card.MAX_CARD_BYTES} bytes; split the task"
    ]


def test_cutter_must_not_write_the_checklist() -> None:
    body = BODY + "\n## Checklist\n\n1. mine\n"
    assert any("leave out '## Checklist'" in e for e in errors_of(card.parse(cutter_card(body=body), require_checklist=False)))


def test_seal_appends_checklist_and_result_is_a_sealed_card() -> None:
    sealed = card.seal(cutter_card(), "1. Reproduce first.")
    assert isinstance(sealed, Ok)
    parsed = card.parse(sealed.value, require_checklist=True)
    assert isinstance(parsed, Ok)
    assert parsed.value.section(Section.CHECKLIST) == "1. Reproduce first."
    assert card.parse(cutter_card(), require_checklist=True) != parsed
    assert "the sealed card has no '## Checklist' section" in errors_of(card.parse(cutter_card(), require_checklist=True))


def test_seal_rejects_invalid_card_and_empty_checklist() -> None:
    assert isinstance(card.seal("nonsense", "1. x"), Err)
    assert errors_of(card.seal(cutter_card(), "  ")) == ["the checklist for kind 'bugfix' is empty"]


@pytest.mark.parametrize("kind", list(Kind))
def test_every_kind_ships_a_checklist_that_seals(kind: Kind) -> None:
    path = card.checklist_path(PACK, kind)
    checklist = path.read_text(encoding="utf-8")
    front = FRONT.replace('kind = "bugfix"', f'kind = "{kind.value}"')
    assert isinstance(card.seal(cutter_card(front=front), checklist), Ok)
    assert "## " not in checklist
