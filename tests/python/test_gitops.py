import subprocess
from pathlib import Path

import pytest

from litetools import gitops
from litetools.result import Err, Ok


def repo_with(tmp_path: Path, files: dict[str, bytes]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def test_tracked_lines_are_stripped_and_cover_subdirectories(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, {"a.txt": b"  one\n", "sub dir/b.txt": b"\ttwo  \r\n"})
    lines = gitops.tracked_lines(repo)
    assert isinstance(lines, Ok)
    assert {"one", "two"} <= lines.value


def test_tracked_lines_ignore_untracked_files(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, {"a.txt": b"one\n"})
    (repo / "new.txt").write_text("written later\n")
    lines = gitops.tracked_lines(repo)
    assert isinstance(lines, Ok) and "written later" not in lines.value


def test_tracked_lines_skip_binary_and_oversized_files(tmp_path: Path) -> None:
    big = b"huge line\n" * (gitops.MAX_SCANNED_FILE_BYTES // 10 + 1)
    repo = repo_with(tmp_path, {"a.txt": b"one\n", "b.bin": b"\xff\xfe\x00binary\n", "big.txt": big})
    lines = gitops.tracked_lines(repo)
    assert isinstance(lines, Ok)
    assert "one" in lines.value and "binary" not in lines.value and "huge line" not in lines.value


def test_tracked_lines_skip_symlinks_even_to_outside_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret line\n")
    repo = repo_with(tmp_path, {"a.txt": b"one\n"})
    (repo / "link").symlink_to(outside)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    lines = gitops.tracked_lines(repo)
    assert isinstance(lines, Ok) and "secret line" not in lines.value


def test_tracked_lines_outside_a_repository_is_an_error(tmp_path: Path) -> None:
    assert isinstance(gitops.tracked_lines(tmp_path), Err)


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout


def rig_with_submodule(tmp_path: Path) -> tuple[Path, Path]:
    """A rig whose main checkout has cloned submodule ``lib`` from ``lib-src``; returns (rig, lib-src)."""
    lib = tmp_path / "lib-src"
    lib.mkdir()
    run_git(lib, "init", "-q", "-b", "main")
    (lib / "lib.txt").write_text("from the submodule\n")
    run_git(lib, "add", "-A")
    run_git(lib, "commit", "-q", "-m", "lib")
    rig = tmp_path / "rig"
    rig.mkdir()
    run_git(rig, "init", "-q", "-b", "main")
    (rig / "README").write_text("rig\n")
    run_git(rig, "add", "-A")
    run_git(rig, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "lib")
    run_git(rig, "commit", "-q", "-m", "add lib")
    return rig, lib


def test_init_submodules_clones_from_the_rigs_copy_without_touching_its_config(tmp_path: Path) -> None:
    rig, lib = rig_with_submodule(tmp_path)
    config_before = (rig / ".git" / "config").read_bytes()
    worktree = tmp_path / "wt"
    run_git(rig, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    subprocess.run(["rm", "-rf", str(lib)], check=True)

    assert gitops.init_submodules(worktree) == Ok(None)

    assert (worktree / "lib" / "lib.txt").read_text() == "from the submodule\n"
    assert (rig / ".git" / "config").read_bytes() == config_before


def test_init_submodules_fetches_a_submodule_the_rig_never_cloned_from_its_remote(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, _ = rig_with_submodule(tmp_path)
    rig = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(source), str(rig)], check=True)
    worktree = tmp_path / "wt"
    run_git(rig, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")

    assert gitops.local_submodule_urls(worktree) == Ok(())
    assert gitops.init_submodules(worktree) == Ok(None)
    assert (worktree / "lib" / "lib.txt").read_text() == "from the submodule\n"


def test_local_submodule_urls_name_the_rigs_clone(tmp_path: Path) -> None:
    rig, _ = rig_with_submodule(tmp_path)
    worktree = tmp_path / "wt"
    run_git(rig, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")

    assert gitops.local_submodule_urls(worktree) == Ok((("lib", str((rig / ".git" / "modules" / "lib").resolve())),))


def test_init_submodules_without_gitmodules_does_nothing(tmp_path: Path) -> None:
    repo = repo_with(tmp_path, {"a.txt": b"a\n"})

    assert gitops.init_submodules(repo) == Ok(None)
