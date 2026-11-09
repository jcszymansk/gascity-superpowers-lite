"""Git operations on the rig repository and an item's worktree.

Landing moves the target branch by compare-and-swap only::

    target missing ──────────────► create at HEAD (refused if HEAD == base)
    target ⊇ HEAD ───────────────► nothing to move
    target ⊂ HEAD (fast-forward) ► update-ref target HEAD <old>
    otherwise ───────────────────► refused: a sibling landed first
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 300
MAX_SCANNED_FILE_BYTES = 1024 * 1024


def git(repo: Path, *args: str) -> Result[str, str]:
    """Run ``git -C repo args...`` and return stdout."""
    log.debug("git -C %s %s", repo, " ".join(args))
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Err(f"git {args[0] if args else ''} could not run: {error}")
    if proc.returncode != 0:
        return Err(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}")
    return Ok(proc.stdout)


def git_ok(repo: Path, *args: str) -> bool:
    """Return True when ``git args...`` exits 0 (for yes/no questions)."""
    return isinstance(git(repo, *args), Ok)


def rev(repo: Path, ref: str) -> Result[str, str]:
    """Resolve ``ref`` to a commit id."""
    out = git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    return Ok(out.value.strip()) if isinstance(out, Ok) else Err(f"{ref} does not resolve to a commit")


def init_submodules(worktree: Path) -> Result[None, str]:
    """Check out the submodules a worktree's ``.gitmodules`` declares, recursively.

    ``git worktree add`` leaves submodule directories empty, and a build that
    includes one (a Gradle ``includeBuild``, say) fails in such a worktree.
    A worktree without ``.gitmodules`` is left alone.
    """
    if not (worktree / ".gitmodules").is_file():
        return Ok(None)
    log.info("initialising submodules in %s", worktree)
    out = git(worktree, "submodule", "update", "--init", "--recursive")
    return Ok(None) if isinstance(out, Ok) else Err(f"could not check out submodules: {out.error}")


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    """Return True when ``older`` is an ancestor of (or equal to) ``newer``."""
    return git_ok(repo, "merge-base", "--is-ancestor", older, newer)


def is_clean(worktree: Path) -> Result[bool, str]:
    """Return whether the worktree has no changes, untracked files included."""
    out = git(worktree, "status", "--porcelain", "--untracked-files=all")
    return Ok(not out.value.strip()) if isinstance(out, Ok) else out


def tracked_lines(worktree: Path) -> Result[frozenset[str], str]:
    """Return every stripped line of the worktree's tracked text files.

    Files that are binary, oversized, symlinks or submodules are skipped: none
    of them is code a card would quote.
    """
    listed = git(worktree, "ls-files", "-z")
    if isinstance(listed, Err):
        return listed
    lines: set[str] = set()
    for name in filter(None, listed.value.split("\0")):
        path = worktree / name
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SCANNED_FILE_BYTES:
                log.debug("not scanning %s", name)
                continue
            data = path.read_bytes()
        except OSError as error:
            return Err(f"cannot read {path}: {error}")
        try:
            lines.update(line.strip() for line in data.decode("utf-8").splitlines())
        except UnicodeDecodeError:
            log.debug("not scanning binary file %s", name)
    return Ok(frozenset(lines))


def reset_to(worktree: Path, commit: str) -> Result[None, str]:
    """Discard every change and commit in ``worktree`` and check out ``commit`` detached.

    Ignored files survive, so build caches are not thrown away with the attempt.
    """
    for args in (("checkout", "--detach", "--force", commit), ("reset", "--hard", commit), ("clean", "-fd")):
        out = git(worktree, *args)
        if isinstance(out, Err):
            return out
    return Ok(None)


def commit_all(worktree: Path, message: str) -> Result[str | None, str]:
    """Stage everything and commit; return the new commit, or None if nothing changed."""
    clean = is_clean(worktree)
    if isinstance(clean, Err):
        return clean
    if clean.value:
        return Ok(None)
    for args in (("add", "-A"), ("commit", "-q", "--no-verify", "-m", message)):
        out = git(worktree, *args)
        if isinstance(out, Err):
            return out
    head = rev(worktree, "HEAD")
    return Ok(head.value) if isinstance(head, Ok) else head


@dataclass(frozen=True, slots=True)
class Diff:
    """An attempt's changes against its base.

    Attributes:
        name_status: ``git diff --name-status -z`` output.
        unified: ``git diff -U0`` output, for the test-integrity check.
        full: ``git diff`` with context, for reviewers and later tiers.
    """

    name_status: str
    unified: str
    full: str


def diff(worktree: Path, base: str) -> Result[Diff, str]:
    """Return the committed changes from ``base`` to ``HEAD``."""
    parts: list[str] = []
    for args in (
        ("diff", "--name-status", "-z", "-M", f"{base}..HEAD"),
        ("diff", "-U0", "--no-color", "-M", f"{base}..HEAD"),
        ("diff", "--no-color", "-M", f"{base}..HEAD"),
    ):
        out = git(worktree, *args)
        if isinstance(out, Err):
            return out
        parts.append(out.value)
    return Ok(Diff(*parts))


@dataclass(frozen=True, slots=True)
class Landed:
    """A successful land.

    Attributes:
        commit: The commit the target branch now contains.
        message: What happened, for the step's close reason.
    """

    commit: str
    message: str


def land(rig: Path, worktree: Path, target: str, base: str, label: str) -> Result[Landed, str]:
    """Move ``refs/heads/target`` to the worktree's HEAD by compare-and-swap.

    Args:
        rig: The rig repository that owns the branch.
        worktree: The item's worktree.
        target: The branch to land on.
        base: The commit the item started from.
        label: A reflog message.

    Returns:
        The landed commit, or the reason the land was refused. A refusal
        changes nothing.
    """
    clean = is_clean(worktree)
    if isinstance(clean, Err):
        return clean
    if not clean.value:
        return Err(f"worktree {worktree} is not clean")
    head_result = rev(worktree, "HEAD")
    if isinstance(head_result, Err):
        return head_result
    head = head_result.value
    if not is_ancestor(rig, base, head):
        return Err(f"HEAD {head} does not descend from base {base}")
    ref = f"refs/heads/{target}"
    old = rev(rig, ref)
    if isinstance(old, Ok):
        if old.value == head or is_ancestor(rig, head, old.value):
            return Ok(Landed(head, f"nothing to move: {target} at {old.value} already contains {head}"))
        if not is_ancestor(rig, old.value, head):
            return Err(f"{target} moved to {old.value}, which HEAD lacks; a sibling landed first")
        listing = git(rig, "worktree", "list", "--porcelain")
        if isinstance(listing, Err):
            return listing
        if f"branch {ref}" in listing.value.splitlines():
            return Err(f"{target} is checked out in a worktree")
        moved = git(rig, "update-ref", "-m", label, ref, head, old.value)
        if isinstance(moved, Err):
            return moved
        message = f"fast-forwarded {target} from {old.value} to {head}"
    elif head == base:
        return Err(f"the item made no commit and {target} does not exist")
    else:
        created = git(rig, "update-ref", "-m", label, ref, head, "")
        if isinstance(created, Err):
            return created
        message = f"created {target} at {head}"
    after = rev(rig, ref)
    if isinstance(after, Err) or not is_ancestor(rig, head, after.value):
        return Err(f"{target} does not contain {head} after landing")
    return Ok(Landed(head, message))
