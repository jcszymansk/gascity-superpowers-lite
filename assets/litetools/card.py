"""The task card: one self-contained unit of work for a cheap executor.

A card is Markdown with TOML front matter between ``+++`` lines::

    +++
    schema = "lite.card.v1"
    id = "smt-12"
    kind = "bugfix"
    files = ["src/parse.rs", "tests/parse.rs"]
    done_when = ["cargo test --test parse"]
    +++

    ## Goal
    ...

The body must hold every section in ``CUTTER_SECTIONS``. ``## Checklist`` is
never written by a model: ``seal`` pastes the kind's checklist from the pack,
so every harness and model gets the same text.

A card holds no implementation. When cards carried code, the executor copied
98% of its diff from them, so the expensive cutter did the work and a cheap
executor's pass proved nothing. Only ``## Context`` and ``## Interfaces`` may
hold fenced code: Context must quote lines that exist in the repository, and
Interfaces is capped at what signatures need. Everything else the cutter
writes shares a size cap small enough that a solution cannot fit in it.
"""

from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

SCHEMA = "lite.card.v1"
FENCE = "+++"
MAX_FILES = 8
MAX_DONE_WHEN = 8
MAX_CARD_BYTES = 32 * 1024
MAX_AUTHORED_BYTES = 8 * 1024
MAX_INTERFACE_CODE_LINES = 40
MAX_INLINE_CODE = 120
MAX_REPORTED_LINES = 5
CHECKLIST_HEADING = "Checklist"


class Kind(Enum):
    """Task kinds that ship a checklist in ``assets/kinds/<value>.md``."""

    BUGFIX = "bugfix"
    TDD_FEATURE = "tdd-feature"


class Section(Enum):
    """Body sections, in the order a card presents them."""

    GOAL = "Goal"
    INTERFACES = "Interfaces"
    CONTEXT = "Context"
    STEPS = "Steps"
    OUT_OF_SCOPE = "Out of scope"
    CHECKLIST = CHECKLIST_HEADING


CUTTER_SECTIONS: tuple[Section, ...] = (
    Section.GOAL,
    Section.INTERFACES,
    Section.CONTEXT,
    Section.STEPS,
    Section.OUT_OF_SCOPE,
)

CODE_FREE_SECTIONS: tuple[Section, ...] = (Section.GOAL, Section.STEPS, Section.OUT_OF_SCOPE)

_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")
_CODE_FENCE = re.compile(r"^\s*(```|~~~)")
_INDENTED_CODE = re.compile(r"^( {4,}|\t)(?![-*+] |\d+[.)] )\S")
_INLINE_CODE = re.compile(r"`([^`\n]*)`")


@dataclass(frozen=True, slots=True)
class Card:
    """A parsed card.

    Attributes:
        card_id: The work bead the card was cut from.
        kind: The task kind, which selects the checklist.
        files: Repository-relative paths the executor may create or change.
        done_when: Shell commands that must all exit 0 in the worktree.
        sections: Body text per section, without the heading line.
    """

    card_id: str
    kind: Kind
    files: tuple[str, ...]
    done_when: tuple[str, ...]
    sections: tuple[tuple[Section, str], ...]

    def section(self, section: Section) -> str:
        """Return the body of ``section``, or an empty string if absent."""
        return next((body for name, body in self.sections if name is section), "")


def _split(text: str) -> Result[tuple[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return Err(f"the card must start with a '{FENCE}' line")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FENCE:
            return Ok(("\n".join(lines[1:index]), "\n".join(lines[index + 1 :])))
    return Err(f"the front matter has no closing '{FENCE}' line")


def _sections(body: str) -> tuple[tuple[tuple[Section, str], ...], list[str]]:
    """Return the recognised sections and every structural error, together."""
    by_title = {section.value: section for section in Section}
    found: list[tuple[Section, list[str]]] = []
    errors: list[str] = []
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            title = match.group("title")
            section = by_title.get(title)
            if section is None:
                errors.append(f"unknown section '## {title}'")
                continue
            if any(name is section for name, _ in found):
                errors.append(f"section '## {title}' appears twice")
                continue
            found.append((section, []))
        elif found:
            found[-1][1].append(line)
        elif line.strip() and "text before the first '## ' section" not in errors:
            errors.append("text before the first '## ' section")
    return tuple((name, "\n".join(lines).strip()) for name, lines in found), errors


def _split_code(text: str) -> tuple[list[str], list[str]]:
    """Return a section's prose lines and its fenced code lines, apart.

    An unclosed fence counts as code up to the end of the section.
    """
    prose: list[str] = []
    code: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _CODE_FENCE.match(line):
            in_fence = not in_fence
        elif in_fence:
            code.append(line)
        else:
            prose.append(line)
    return prose, code


def _code_rule_errors(sections: tuple[tuple[Section, str], ...]) -> list[str]:
    """Return every way the sections break the no-implementation rule."""
    errors: list[str] = []
    authored_bytes = 0
    for section, text in sections:
        if section is Section.CHECKLIST:
            continue
        prose, code = _split_code(text)
        authored_bytes += len("\n".join(prose).encode("utf-8"))
        if section is not Section.CONTEXT:
            authored_bytes += len("\n".join(code).encode("utf-8"))
        if section is Section.INTERFACES and len(code) > MAX_INTERFACE_CODE_LINES:
            errors.append(
                f"'## Interfaces' has {len(code)} lines of code; the cap is "
                f"{MAX_INTERFACE_CODE_LINES}: give signatures and types, not bodies"
            )
        if section not in CODE_FREE_SECTIONS:
            continue
        where = f"'## {section.value}'"
        if code or "```" in text or "~~~" in text:
            errors.append(f"{where} holds a code block: describe the behaviour, the executor writes the code")
        if any(_INDENTED_CODE.match(line) for line in prose):
            errors.append(f"{where} holds a line indented like code: describe the behaviour instead")
        if any(len(span) > MAX_INLINE_CODE for span in _INLINE_CODE.findall(text)):
            errors.append(f"{where} holds inline code over {MAX_INLINE_CODE} characters: describe it instead")
    if authored_bytes > MAX_AUTHORED_BYTES:
        errors.append(
            f"the card has {authored_bytes} bytes outside quoted code; the cap is {MAX_AUTHORED_BYTES}: "
            "cut any solution out of it, or split the task"
        )
    return errors


def unquoted_context_lines(card: Card, known_lines: frozenset[str]) -> list[str]:
    """Return an error for ``## Context`` code that is not in the repository.

    Args:
        card: The parsed card.
        known_lines: Every line of the repository's tracked files, stripped.

    Returns:
        Errors naming the first offending lines; empty when every line is real.
    """
    _, code = _split_code(card.section(Section.CONTEXT))
    missing = [line.strip() for line in code if line.strip() and line.strip() not in known_lines]
    if not missing:
        return []
    shown = "; ".join(repr(line) for line in missing[:MAX_REPORTED_LINES])
    return [
        f"'## Context' code must quote the repository exactly, with no new code, line numbers or elisions; "
        f"{len(missing)} lines are not in it, such as {shown}"
    ]


def _relative_path_error(path: str) -> str | None:
    if not path or path != path.strip():
        return f"file path {path!r} is empty or has surrounding spaces"
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or "\\" in path:
        return f"file path {path!r} must be relative to the repository and stay inside it"
    return None


def _string_list(meta: dict[str, object], key: str, limit: int) -> Result[tuple[str, ...], str]:
    value = meta.get(key)
    if not isinstance(value, list) or not value:
        return Err(f"'{key}' must be a non-empty list of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        return Err(f"every entry of '{key}' must be a non-empty string")
    if len(value) > limit:
        return Err(f"'{key}' has {len(value)} entries; the cap is {limit}, so split the task")
    items = tuple(str(item) for item in value)
    if len(set(items)) != len(items):
        return Err(f"'{key}' lists an entry twice")
    return Ok(items)


def parse(text: str, *, require_checklist: bool) -> Result[Card, list[str]]:
    """Parse and validate a card.

    Args:
        text: The card file's content.
        require_checklist: True for a sealed card, which must carry the
            pasted checklist; False for a card as the cutter wrote it, which
            must not carry one.

    Returns:
        The card, or every validation error found.
    """
    if len(text.encode("utf-8")) > MAX_CARD_BYTES:
        return Err([f"the card is over {MAX_CARD_BYTES} bytes; split the task"])
    split = _split(text)
    if isinstance(split, Err):
        return Err([split.error])
    front, body = split.value
    try:
        meta: dict[str, object] = tomllib.loads(front)
    except tomllib.TOMLDecodeError as error:
        return Err([f"the front matter is not valid TOML: {error}"])

    errors: list[str] = []
    allowed = {"schema", "id", "kind", "files", "done_when"}
    errors.extend(f"unknown front matter key '{key}'" for key in sorted(set(meta) - allowed))
    if meta.get("schema") != SCHEMA:
        errors.append(f"'schema' must be \"{SCHEMA}\"")
    card_id = meta.get("id")
    if not isinstance(card_id, str) or not card_id.strip():
        errors.append("'id' must name the work bead")
    kinds = {kind.value: kind for kind in Kind}
    kind = kinds.get(str(meta.get("kind")))
    if kind is None:
        errors.append(f"'kind' must be one of {', '.join(sorted(kinds))}")

    files = _string_list(meta, "files", MAX_FILES)
    if isinstance(files, Err):
        errors.append(files.error)
    else:
        errors.extend(e for e in map(_relative_path_error, files.value) if e is not None)
    done_when = _string_list(meta, "done_when", MAX_DONE_WHEN)
    if isinstance(done_when, Err):
        errors.append(done_when.error)

    sections, section_errors = _sections(body)
    errors.extend(section_errors)
    errors.extend(_code_rule_errors(sections))
    present = {name for name, _ in sections}
    for section in CUTTER_SECTIONS:
        if section not in present:
            errors.append(f"missing section '## {section.value}'")
        elif not next(text for name, text in sections if name is section):
            errors.append(f"section '## {section.value}' is empty")
    if require_checklist and Section.CHECKLIST not in present:
        errors.append("the sealed card has no '## Checklist' section")
    if not require_checklist and Section.CHECKLIST in present:
        errors.append("leave out '## Checklist'; it is pasted from the pack when the card is sealed")

    if errors or isinstance(files, Err) or isinstance(done_when, Err):
        log.debug("card rejected: %s", errors)
        return Err(errors)
    if not isinstance(card_id, str) or kind is None:
        return Err(["internal: id or kind passed validation without a value"])
    return Ok(Card(card_id.strip(), kind, files.value, done_when.value, sections))


def checklist_path(pack_dir: Path, kind: Kind) -> Path:
    """Return the checklist file the pack ships for ``kind``."""
    return pack_dir / "assets" / "kinds" / f"{kind.value}.md"


def seal(text: str, checklist: str) -> Result[str, list[str]]:
    """Validate a cutter's card and append the kind checklist to it.

    Args:
        text: The card as the cutter wrote it, without a checklist.
        checklist: The checklist text for the card's kind.

    Returns:
        The sealed card text, or the validation errors.
    """
    parsed = parse(text, require_checklist=False)
    if isinstance(parsed, Err):
        return parsed
    if not checklist.strip():
        return Err([f"the checklist for kind '{parsed.value.kind.value}' is empty"])
    sealed = f"{text.rstrip()}\n\n## {CHECKLIST_HEADING}\n\n{checklist.strip()}\n"
    reparsed = parse(sealed, require_checklist=True)
    if isinstance(reparsed, Err):
        return reparsed
    return Ok(sealed)
