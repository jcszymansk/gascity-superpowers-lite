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


def diff_scope(changes: tuple[ChangedPath, ...], allowed: tuple[str, ...]) -> CheckResult:
    """Fail when the attempt touched a path the card does not list.

    A rename counts as touching both its old and its new path.
    """
    permitted = set(allowed)
    touched = sorted({p for c in changes for p in (c.path, c.old_path)})
    outside = [path for path in touched if path not in permitted]
    details = tuple(f"changed a file outside the card's files: {path}" for path in outside)
    return CheckResult("diff-scope", not outside, details)


_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|androidTest|testFixtures)/"
    r"|(^|/)test_[^/]*\.py$|_test\.(go|py|rs|exs?)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|Tests?\.(kt|java|cs|swift)$"
)
_TEST_DECLARATION = re.compile(
    r"#\[(tokio::)?test\]|@Test\b|@ParameterizedTest\b|\bdef test_|\bfunc Test[A-Z_]"
    r"|^\s*(it|test)\s*\(|^\s*fn test_"
)
_SKIP_MARKER = re.compile(
    r"#\[ignore\b|@Ignore\b|@Disabled\b|pytest\.mark\.(skip|xfail)\b|unittest\.skip\b"
    r"|\b(it|test|describe)\.(skip|todo)\s*\(|\bx(it|describe|test)\s*\(|\bt\.Skip(Now|f)?\("
    r"|@pytest\.skip\b|\bpytest\.skip\("
)


def is_test_path(path: str) -> bool:
    """Return True when ``path`` looks like a test file."""
    return bool(_TEST_PATH.search(PurePosixPath(path).as_posix()))


def tests_intact(changes: tuple[ChangedPath, ...], unified_diff: str) -> CheckResult:
    """Fail when the attempt deletes tests or adds skip markers.

    Args:
        changes: The attempt's changed paths.
        unified_diff: ``git diff -U0`` output for the same range.
    """
    details: list[str] = [
        f"deleted test file: {c.path}" for c in changes if c.status == "D" and is_test_path(c.path)
    ]
    removed: dict[str, int] = {}
    added: dict[str, int] = {}
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
        if line.startswith("+"):
            text = line[1:]
            if _SKIP_MARKER.search(text):
                details.append(f"added a skip marker in {current or 'a deleted file'}: {text.strip()}")
            if _TEST_DECLARATION.search(text):
                added[current] = added.get(current, 0) + 1
        elif line.startswith("-") and _TEST_DECLARATION.search(line[1:]):
            removed[current] = removed.get(current, 0) + 1
    for path, count in sorted(removed.items()):
        net = count - added.get(path, 0)
        if net > 0 and path:
            details.append(f"removed {net} test declaration(s) from {path}")
    return CheckResult("tests-intact", not details, tuple(details))


def _tail(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else "…" + text[-OUTPUT_LIMIT:]


def card_done(commands: tuple[str, ...], workdir: Path, timeout_seconds: int) -> CheckResult:
    """Run every ``done_when`` command in ``workdir``; fail if any fails.

    Every command runs even after a failure, so the findings name all of them.
    """
    details: list[str] = []
    for command in commands:
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
            details.append(f"timed out after {timeout_seconds}s: {command}")
            continue
        log.debug("done_when: %r exited %d", command, proc.returncode)
        if proc.returncode != 0:
            output = _tail((proc.stdout + proc.stderr).strip())
            details.append(f"exit {proc.returncode}: {command}\n{output}")
    return CheckResult("card-done", not details, tuple(details))
