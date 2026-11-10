from pathlib import Path

import pytest

from litetools import checks
from litetools.checks import ChangedPath


def test_parse_name_status_handles_renames_and_plain_entries() -> None:
    raw = "M\0src/a.rs\0R087\0old/b.rs\0new/b.rs\0D\0tests/c.rs\0A\0d e.txt\0"
    assert checks.parse_name_status(raw) == (
        ChangedPath("M", "src/a.rs", "src/a.rs"),
        ChangedPath("R", "new/b.rs", "old/b.rs"),
        ChangedPath("D", "tests/c.rs", "tests/c.rs"),
        ChangedPath("A", "d e.txt", "d e.txt"),
    )
    assert checks.parse_name_status("") == ()


def test_diff_scope_passes_inside_the_card_files() -> None:
    result = checks.diff_scope((ChangedPath("M", "src/a.rs", "src/a.rs"),), ("src/a.rs", "tests/a.rs"))
    assert result.passed and result.details == ()
    assert result.name == "diff-scope"


def test_diff_scope_names_every_file_outside_the_card() -> None:
    changes = (
        ChangedPath("M", "src/a.rs", "src/a.rs"),
        ChangedPath("A", "src/extra.rs", "src/extra.rs"),
        ChangedPath("R", "src/a2.rs", "src/old.rs"),
    )
    result = checks.diff_scope(changes, ("src/a.rs", "src/a2.rs"))
    assert not result.passed
    assert result.details == (
        "changed a file outside the card's files: src/extra.rs",
        "changed a file outside the card's files: src/old.rs",
    )


@pytest.mark.parametrize(
    "path",
    ["tests/parse.rs", "app/src/test/kotlin/FooTest.kt", "pkg/a_test.go", "test_x.py", "web/a.spec.ts", "FooTests.swift", "x/__tests__/a.js"],
)
def test_test_paths_are_recognised(path: str) -> None:
    assert checks.is_test_path(path)


@pytest.mark.parametrize("path", ["src/testing.rs", "src/contest.py", "README.md", "src/lib.rs"])
def test_non_test_paths_are_not(path: str) -> None:
    assert not checks.is_test_path(path)


def diff(path: str, *lines: str) -> str:
    return "\n".join([f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", "@@ -1,1 +1,1 @@", *lines])


def test_no_skip_markers_passes_for_added_tests() -> None:
    result = checks.no_skip_markers(diff("tests/a.rs", "+#[test]", "+fn empty() {}"))
    assert result.passed, result.details


@pytest.mark.parametrize(
    "marker",
    ["#[ignore]", "@Ignore", "@Disabled", "@pytest.mark.skip(reason='x')", "it.skip('a', () => {})", "xit('a')", "t.Skip(\"later\")", "@unittest.skip('x')", "pytest.skip('x')"],
)
def test_no_skip_markers_flags_added_skip_markers(marker: str) -> None:
    result = checks.no_skip_markers(diff("tests/a.rs", f"+{marker}"))
    assert result.name == "no-skip-markers"
    assert not result.passed
    assert result.details == (f"added a skip marker in tests/a.rs: {marker}",)


def test_no_skip_markers_ignores_removed_markers() -> None:
    assert checks.no_skip_markers(diff("tests/a.rs", "-#[ignore]")).passed


def test_no_skip_markers_does_not_mistake_content_for_headers() -> None:
    text = diff("tests/a.py", "+++ looks like a header", "-def test_a():", "+def test_a():")
    assert checks.no_skip_markers(text).passed


def test_removed_tests_is_empty_when_tests_are_only_added_or_renamed() -> None:
    added = diff("tests/a.rs", "+#[test]", "+fn empty() {}")
    assert checks.removed_tests((ChangedPath("M", "tests/a.rs", "tests/a.rs"),), added) == ()
    renamed = diff("pkg/a_test.go", "-func TestA(t *testing.T) {", "+func TestRenamed(t *testing.T) {")
    assert checks.removed_tests((), renamed) == ()


def test_removed_tests_names_deleted_test_files_but_not_other_deleted_files() -> None:
    changes = (ChangedPath("D", "tests/a.rs", "tests/a.rs"), ChangedPath("D", "src/old.rs", "src/old.rs"))
    assert checks.removed_tests(changes, "") == ("deleted test file: tests/a.rs",)


def test_removed_tests_counts_net_removals_per_file_and_names_them() -> None:
    text = diff("pkg/a_test.go", "-func TestA(t *testing.T) {", "-func TestB(t *testing.T) {", "+func TestA(t *testing.T) {")
    assert checks.removed_tests((), text) == (
        "pkg/a_test.go: 1 test declaration(s) fewer; removed: func TestA(t *testing.T) {; func TestB(t *testing.T) {",
    )


def test_removed_tests_names_a_kotlin_test_by_the_line_after_its_annotation() -> None:
    text = diff("app/src/test/FooTest.kt", "-    @Test", "-    fun artworkBumpsTheRevision() {", "-        assertEquals(1, x)")
    assert checks.removed_tests((), text) == (
        "app/src/test/FooTest.kt: 1 test declaration(s) fewer; removed: fun artworkBumpsTheRevision() {",
    )


def test_removed_tests_keeps_an_annotation_whose_next_line_was_not_removed() -> None:
    text = diff("app/src/test/FooTest.kt", "-    @Test", "+    @Test")
    assert checks.removed_tests((), text) == ()
    lone = diff("app/src/test/FooTest.kt", "-    @Test")
    assert checks.removed_tests((), lone) == ("app/src/test/FooTest.kt: 1 test declaration(s) fewer; removed: @Test",)


def test_removed_tests_reports_each_file_separately_in_path_order() -> None:
    text = diff("tests/b.py", "-def test_b():") + "\n" + diff("tests/a.py", "-def test_a():", "-def test_c():", "+def test_d():")
    assert checks.removed_tests((), text) == (
        "tests/a.py: 1 test declaration(s) fewer; removed: def test_a():; def test_c():",
        "tests/b.py: 1 test declaration(s) fewer; removed: def test_b():",
    )


def test_card_done_runs_every_command_and_reports_each_failure(tmp_path: Path) -> None:
    (tmp_path / "flag").write_text("x")
    result = checks.card_done(("test -f flag", "echo boom >&2; exit 3", "exit 4"), tmp_path, timeout_seconds=10)
    assert not result.passed
    assert result.details == ("exit 3: echo boom >&2; exit 3\nboom", "exit 4: exit 4\n")
    assert checks.card_done(("true",), tmp_path, timeout_seconds=10).passed


def test_card_done_reports_timeouts(tmp_path: Path) -> None:
    result = checks.card_done(("sleep 5",), tmp_path, timeout_seconds=1)
    assert result.details == ("timed out after 1s: sleep 5",)


def test_card_done_truncates_long_output(tmp_path: Path) -> None:
    result = checks.card_done(("yes x | head -c 20000; exit 1",), tmp_path, timeout_seconds=10)
    assert len(result.details[0]) < checks.OUTPUT_LIMIT + 200
    assert "…" in result.details[0]


def test_added_lines_skip_headers_and_keep_content() -> None:
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n-old\n+new line\n+\n+++not a header\n"
    assert checks.added_lines(diff) == ("new line", "")
    assert checks.added_lines("") == ()
