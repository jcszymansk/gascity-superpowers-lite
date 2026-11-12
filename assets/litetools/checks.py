"""Checks run on every attempt before any model reviews it.

Each check returns a ``CheckResult``; ``passed`` is false when it found a
problem. The checks only read: the caller gathers git output and runs them.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

OUTPUT_LIMIT = 8000


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One check's verdict.

    Attributes:
        name: The check's name, as recorded on the item.
        passed: True when the check found nothing wrong.
        details: Human-readable findings, one per line.
    """

    name: str
    passed: bool
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChangedPath:
    """One entry of ``git diff --name-status``.

    Attributes:
        status: The status letter (A, M, D, R, C, T).
        path: The path after the change.
        old_path: The path before a rename or copy, else equal to ``path``.
    """

    status: str
    path: str
    old_path: str


def parse_name_status(output: str) -> tuple[ChangedPath, ...]:
    """Parse ``git diff --name-status -z`` output."""
    fields = [field for field in output.split("\0") if field]
    changes: list[ChangedPath] = []
    index = 0
    while index < len(fields):
        status = fields[index][:1]
        if status in ("R", "C"):
            old, new = fields[index + 1], fields[index + 2]
            changes.append(ChangedPath(status, new, old))
            index += 3
        else:
            path = fields[index + 1]
            changes.append(ChangedPath(status, path, path))
            index += 2
    return tuple(changes)


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """Translate a card ``files`` entry into a regex over a whole repository path.

    ``*`` matches within one path segment, ``?`` one character of a segment, and a
    segment that is exactly ``**`` matches any number of segments: ``app/**/Foo*.kt``
    covers ``app/Foo.kt`` and ``app/a/b/FooTest.kt``, and a trailing ``app/**`` covers
    everything under ``app/``. Anything else is literal, so a plain path matches only itself.
    """
    parts = pattern.split("/")
    out: list[str] = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            out.append(".+" if last else "(?:[^/]+/)*")
            continue
        segment = "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in part)
        out.append(segment if last else segment + "/")
    return re.compile("".join(out))


def path_matches(pattern: str, path: str) -> bool:
    """Return True when the repository path ``path`` is covered by the card entry ``pattern``."""
    return _pattern_regex(pattern).fullmatch(path) is not None


def touched_paths(changes: tuple[ChangedPath, ...]) -> tuple[str, ...]:
    """Return every path an attempt touched, sorted; a rename touches its old and new path."""
    return tuple(sorted({p for c in changes for p in (c.path, c.old_path)}))


def non_empty_diff(changes: tuple[ChangedPath, ...]) -> CheckResult:
    """Fail when the attempt changed nothing."""
    return CheckResult("non-empty-diff", bool(changes), () if changes else ("the attempt changed nothing",))


def outside_files(changes: tuple[ChangedPath, ...], allowed: tuple[str, ...]) -> tuple[str, ...]:
    """List the paths an attempt touched that no entry of the card's ``files`` covers.

    The list is review input, not a check: a change can need a file the cutter could not
    foresee (a caller of a renamed method, a fixture, a regenerated baseline), and only a
    reviewer can tell that from wandering off the task.

    Args:
        changes: The attempt's changed paths.
        allowed: The card's ``files`` entries, paths or patterns.

    Returns:
        The uncovered paths, sorted.
    """
    regexes = [_pattern_regex(pattern) for pattern in allowed]
    return tuple(path for path in touched_paths(changes) if not any(r.fullmatch(path) for r in regexes))


_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|androidTest|testFixtures)/"
    r"|(^|/)test_[^/]*\.py$|_test\.(go|py|rs|exs?)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|Tests?\.(kt|java|cs|swift)$"
)
_TEST_DECLARATION = re.compile(
    r"#\[(tokio::)?test\]|@Test\b|@ParameterizedTest\b|\bdef test_|\bfunc Test[A-Z_]"
    r"|^\s*(it|test)\s*\(|^\s*fn test_"
)
_BARE_ANNOTATION = re.compile(r"^@\w+(\(.*\))?$")
_SKIP_MARKER = re.compile(
    r"#\[ignore\b|@Ignore\b|@Disabled\b|pytest\.mark\.(skip|xfail)\b|unittest\.skip\b"
    r"|\b(it|test|describe)\.(skip|todo)\s*\(|\bx(it|describe|test)\s*\(|\bt\.Skip(Now|f)?\("
    r"|@pytest\.skip\b|\bpytest\.skip\("
)


def is_test_path(path: str) -> bool:
    """Return True when ``path`` looks like a test file."""
    return bool(_TEST_PATH.search(PurePosixPath(path).as_posix()))


def added_lines(unified_diff: str) -> tuple[str, ...]:
    """Return the lines a unified diff adds, without their ``+``."""
    return tuple(line[1:] for line in unified_diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def _diff_lines(unified_diff: str) -> list[tuple[str, str, str]]:
    """Split ``git diff -U0`` output into (new path, sign, text) for each added or removed line.

    The path is empty for a deleted file. Header lines are skipped by position, so content
    that looks like a header (``+++ x``) still counts as content.
    """
    lines: list[tuple[str, str, str]] = []
    current = ""
    in_header = False
    for line in unified_diff.splitlines():
        if line.startswith("diff --git "):
            in_header, current = True, ""
            continue
        if in_header:
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else ""
            elif line.startswith("@@"):
                in_header = False
            continue
        if line[:1] in ("+", "-"):
            lines.append((current, line[0], line[1:]))
    return lines


def no_skip_markers(unified_diff: str) -> CheckResult:
    """Fail when the attempt adds a skip or ignore marker.

    A skipped test hides a failure while looking kept, so no card can ask for one.

    Args:
        unified_diff: ``git diff -U0`` output for the attempt.
    """
    details = tuple(
        f"added a skip marker in {path or 'a deleted file'}: {text.strip()}"
        for path, sign, text in _diff_lines(unified_diff)
        if sign == "+" and _SKIP_MARKER.search(text)
    )
    return CheckResult("no-skip-markers", not details, details)


def removed_tests(changes: tuple[ChangedPath, ...], unified_diff: str) -> tuple[str, ...]:
    """List the tests an attempt removes, for the reviewer to judge.

    Removing a test is right when the card asks for it or the diff deletes what the test
    exercised, so this is review input, not a check. It names deleted test files and, per
    file, the test declarations removed on net (a renamed test is no removal). A bare
    annotation such as ``@Test`` is named by the removed line after it.

    Args:
        changes: The attempt's changed paths.
        unified_diff: ``git diff -U0`` output for the same range.

    Returns:
        One line per deleted test file and per file that loses declarations.
    """
    found = [f"deleted test file: {c.path}" for c in changes if c.status == "D" and is_test_path(c.path)]
    lines = _diff_lines(unified_diff)
    removed: dict[str, list[str]] = {}
    added: dict[str, int] = {}
    for index, (path, sign, text) in enumerate(lines):
        if not path or not _TEST_DECLARATION.search(text):
            continue
        if sign == "+":
            added[path] = added.get(path, 0) + 1
            continue
        name = text.strip()
        following = lines[index + 1] if index + 1 < len(lines) else None
        if _BARE_ANNOTATION.match(name) and following is not None and following[:2] == (path, "-"):
            name = following[2].strip()
        removed.setdefault(path, []).append(name)
    for path, names in sorted(removed.items()):
        net = len(names) - added.get(path, 0)
        if net > 0:
            found.append(f"{path}: {net} test declaration(s) fewer; removed: " + "; ".join(names))
    return tuple(found)


def _tail(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else "…" + text[-OUTPUT_LIMIT:]


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """How one shell command ended.

    Attributes:
        command: The command as given.
        exit_code: Its exit status, or None when it timed out.
        output: The tail of its combined stdout and stderr.
    """

    command: str
    exit_code: int | None
    output: str

    @property
    def passed(self) -> bool:
        """True when the command exited 0."""
        return self.exit_code == 0

    def finding(self, timeout_seconds: int) -> str:
        """The line a failed command contributes to the card-done findings."""
        if self.exit_code is None:
            return f"timed out after {timeout_seconds}s: {self.command}"
        return f"exit {self.exit_code}: {self.command}\n{self.output}"


def run_command(command: str, workdir: Path, timeout_seconds: int) -> CommandOutcome:
    """Run ``command`` with ``sh -c`` in ``workdir`` and keep the tail of its output."""
    log.info("done_when: running %r in %s", command, workdir)
    try:
        proc = subprocess.run(
            ["sh", "-c", command],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandOutcome(command, None, "")
    log.debug("done_when: %r exited %d", command, proc.returncode)
    return CommandOutcome(command, proc.returncode, _tail((proc.stdout + proc.stderr).strip()))


def card_done_from(outcomes: tuple[CommandOutcome, ...], timeout_seconds: int) -> CheckResult:
    """The card-done check over commands that already ran."""
    details = tuple(o.finding(timeout_seconds) for o in outcomes if not o.passed)
    return CheckResult("card-done", not details, details)


def card_done(commands: tuple[str, ...], workdir: Path, timeout_seconds: int) -> CheckResult:
    """Run every ``done_when`` command in ``workdir``; fail if any fails.

    Every command runs even after a failure, so the findings name all of them.
    """
    outcomes = tuple(run_command(c, workdir, timeout_seconds) for c in commands)
    return card_done_from(outcomes, timeout_seconds)