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


FENCED = "```kotlin\nfun main() {\n}\n```"


def body_with(section: str, text: str) -> str:
    assert f"## {section}\n\n" in BODY
    return BODY.replace(f"## {section}\n\n", f"## {section}\n\n{text}\n\n")


@pytest.mark.parametrize("section", ["Goal", "Steps", "Out of scope"])
@pytest.mark.parametrize("block", [FENCED, "~~~\ncode\n~~~", "```\nunclosed fence"])
def test_code_blocks_are_refused_in_prose_sections(section: str, block: str) -> None:
    errors = errors_of(card.parse(cutter_card(body=body_with(section, block)), require_checklist=False))
    assert any(f"'## {section}' holds a code block" in error for error in errors)


@pytest.mark.parametrize("section", ["Interfaces", "Context"])
def test_code_blocks_are_allowed_in_interfaces_and_context(section: str) -> None:
    assert isinstance(card.parse(cutter_card(body=body_with(section, FENCED)), require_checklist=False), Ok)


@pytest.mark.parametrize("line", ["    val x = 1", "\tval x = 1", "        return x"])
def test_indented_code_is_refused_in_steps(line: str) -> None:
    text = f"1. Add this:\n{line}"
    errors = errors_of(card.parse(cutter_card(body=body_with("Steps", text)), require_checklist=False))
    assert any("indented like code" in error for error in errors)


@pytest.mark.parametrize("line", ["    - a nested bullet", "    1. a nested step", "    2) another", "   continued item text"])
def test_list_continuations_are_not_indented_code(line: str) -> None:
    assert isinstance(card.parse(cutter_card(body=body_with("Steps", line)), require_checklist=False), Ok)


def test_inline_code_cap_is_exact() -> None:
    at_cap = "`" + "x" * card.MAX_INLINE_CODE + "`"
    over = "`" + "x" * (card.MAX_INLINE_CODE + 1) + "`"
    assert isinstance(card.parse(cutter_card(body=body_with("Steps", at_cap)), require_checklist=False), Ok)
    errors = errors_of(card.parse(cutter_card(body=body_with("Steps", over)), require_checklist=False))
    assert any("inline code over" in error for error in errors)


def test_long_prose_between_inline_code_spans_is_not_inline_code() -> None:
    text = "`short` " + "word " * 50 + "`also short`"
    assert isinstance(card.parse(cutter_card(body=body_with("Steps", text)), require_checklist=False), Ok)


def test_interface_code_cap_is_exact() -> None:
    def block(lines: int) -> str:
        return "```\n" + "fun f()\n" * lines + "```"

    allowed = body_with("Interfaces", block(card.MAX_INTERFACE_CODE_LINES))
    assert isinstance(card.parse(cutter_card(body=allowed), require_checklist=False), Ok)
    over = body_with("Interfaces", block(card.MAX_INTERFACE_CODE_LINES + 1))
    errors = errors_of(card.parse(cutter_card(body=over), require_checklist=False))
    assert any("'## Interfaces' has 41 lines of code" in error for error in errors)


def test_long_cards_have_no_size_cap_outside_the_whole_card_limit() -> None:
    for section, text in (("Steps", "word " * 4000), ("Context", "word " * 4000)):
        assert isinstance(card.parse(cutter_card(body=body_with(section, text)), require_checklist=False), Ok), section


def sealed_card(body: str) -> card.Card:
    parsed = card.parse(cutter_card(body=body), require_checklist=False)
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def test_overlap_counts_added_lines_the_card_wrote() -> None:
    written = sealed_card(body_with("Steps", "Call it like this:\n\n`val path = buildPath(first)` once."))
    plain = sealed_card(body_with("Steps", "val path = buildPath(first)"))
    added = ("val path = buildPath(first)", "  val other = somethingElse()  ")
    assert card.overlap(written, added) == card.Overlap(0, 2)
    assert card.overlap(plain, added) == card.Overlap(1, 2)


def test_overlap_counts_interface_code_but_not_quoted_context() -> None:
    interfaces = sealed_card(body_with("Interfaces", "```\nfun encode(entries: List<Entry>): String\n```"))
    context = sealed_card(body_with("Context", "```\nfun encode(entries: List<Entry>): String\n```"))
    added = ("    fun encode(entries: List<Entry>): String",)
    assert card.overlap(interfaces, added) == card.Overlap(1, 1)
    assert card.overlap(context, added) == card.Overlap(0, 1)


def test_overlap_ignores_short_lines_and_the_checklist() -> None:
    short = "x" * (card.MIN_OVERLAP_LINE_CHARS - 1)
    exact = "y" * card.MIN_OVERLAP_LINE_CHARS
    sealed = card.seal(cutter_card(body=body_with("Steps", f"{short}\n{exact}")), "- run every done_when command")
    assert isinstance(sealed, Ok)
    parsed = card.parse(sealed.value, require_checklist=True)
    assert isinstance(parsed, Ok)
    assert card.overlap(parsed.value, (short, exact, "- run every done_when command")) == card.Overlap(1, 2)
    assert str(card.Overlap(1, 2)) == "1/2"


def parsed_with_context(text: str) -> card.Card:
    parsed = card.parse(cutter_card(body=body_with("Context", text)), require_checklist=False)
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def test_context_lines_found_in_the_repository_pass_whatever_their_indent() -> None:
    known = frozenset({"fun main() {", "}"})
    assert card.unquoted_context_lines(parsed_with_context("```\n    fun main() {\n\n}\n```"), known) == []


def test_context_lines_outside_fences_are_prose() -> None:
    assert card.unquoted_context_lines(parsed_with_context("src/a.kt:1-2 holds it."), frozenset()) == []


def test_new_code_in_context_is_refused_and_named() -> None:
    errors = card.unquoted_context_lines(parsed_with_context(FENCED), frozenset({"}"}))
    assert len(errors) == 1 and "1 lines are not in it" in errors[0] and "fun main() {" in errors[0]


def test_only_the_first_missing_context_lines_are_shown() -> None:
    code = "```\n" + "".join(f"line{i}\n" for i in range(card.MAX_REPORTED_LINES + 2)) + "```"
    errors = card.unquoted_context_lines(parsed_with_context(code), frozenset())
    assert f"{card.MAX_REPORTED_LINES + 2} lines" in errors[0]
    assert f"line{card.MAX_REPORTED_LINES - 1}" in errors[0] and f"line{card.MAX_REPORTED_LINES}" not in errors[0]


def test_the_example_card_seals() -> None:
    text = (PACK / "assets" / "templates" / "card-example.md").read_text(encoding="utf-8")
    checklist = (PACK / "assets" / "kinds" / "bugfix.md").read_text(encoding="utf-8")
    assert isinstance(card.seal(text, checklist), Ok)


def test_the_template_obeys_the_rule() -> None:
    text = (PACK / "assets" / "templates" / "card.md").read_text(encoding="utf-8")
    body = text.split("+++", 2)[2]
    assert isinstance(card.parse(cutter_card(body=body), require_checklist=False), Ok)
