import subprocess
from pathlib import Path

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
