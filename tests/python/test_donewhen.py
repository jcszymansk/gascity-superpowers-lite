"""Tests for the detached done_when runner's records."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from litetools import checks, donewhen
from litetools.result import Ok


def spec(tmp_path: Path, commands: tuple[str, ...] = ("true",), head: str = "abc") -> donewhen.Spec:
    return donewhen.Spec(head, commands, tmp_path, 60)


def state(tmp_path: Path) -> donewhen.State:
    root = tmp_path / "checks"
    root.mkdir(exist_ok=True)
    return donewhen.State(root)


def write_result(st: donewhen.State, head: str, commands: list[str], details: object) -> None:
    st.result_file.write_text(json.dumps({"head": head, "commands": commands, "details": details}))


def test_result_is_returned_only_for_the_same_commit_and_commands(tmp_path: Path) -> None:
    st = state(tmp_path)
    write_result(st, "abc", ["true"], [])
    passed = donewhen.result(st, spec(tmp_path))
    assert passed is not None and passed.passed and passed.name == "card-done"
    assert donewhen.result(st, spec(tmp_path, head="other")) is None
    assert donewhen.result(st, spec(tmp_path, commands=("false",))) is None


def test_a_failed_result_carries_its_details(tmp_path: Path) -> None:
    st = state(tmp_path)
    write_result(st, "abc", ["true"], ["exit 1: false"])
    failed = donewhen.result(st, spec(tmp_path))
    assert failed is not None and not failed.passed and failed.details == ("exit 1: false",)


def test_a_malformed_or_missing_result_is_none(tmp_path: Path) -> None:
    st = state(tmp_path)
    assert donewhen.result(st, spec(tmp_path)) is None
    write_result(st, "abc", ["true"], "not a list")
    assert donewhen.result(st, spec(tmp_path)) is None
    st.result_file.write_text("{not json")
    assert donewhen.result(st, spec(tmp_path)) is None


def test_a_run_with_no_pid_yet_counts_as_running_only_within_the_grace(tmp_path: Path) -> None:
    st = state(tmp_path)
    st.run_file.write_text(json.dumps({"head": "abc", "commands": ["true"]}))
    started = st.run_file.stat().st_mtime
    assert donewhen.running(st, spec(tmp_path), started + 1)
    assert not donewhen.running(st, spec(tmp_path), started + donewhen.STARTING_GRACE_SECONDS + 1)


def test_a_run_for_another_commit_or_a_dead_pid_is_not_running(tmp_path: Path) -> None:
    st = state(tmp_path)
    st.run_file.write_text(json.dumps({"head": "abc", "commands": ["true"]}))
    st.pid_file.write_text("999999999\n")
    assert not donewhen.running(st, spec(tmp_path), time.time())
    assert not donewhen.running(st, spec(tmp_path, head="other"), time.time())


def test_await_reuses_a_finished_result_without_starting_a_run(tmp_path: Path) -> None:
    st = state(tmp_path)
    write_result(st, "abc", ["true"], [])
    waited = donewhen.await_result(st, spec(tmp_path), 0)
    assert isinstance(waited, Ok) and waited.value is not None and waited.value.passed
    assert not st.run_file.exists()


def test_await_runs_the_commands_in_a_detached_runner(tmp_path: Path) -> None:
    st = state(tmp_path)
    marker = tmp_path / "ran"
    waited = donewhen.await_result(st, spec(tmp_path, commands=(f"echo x >> {marker}", "exit 3")), 30)
    assert isinstance(waited, Ok)
    outcome = waited.value
    assert outcome is not None and not outcome.passed
    assert outcome.details[0].startswith("exit 3: exit 3")
    assert marker.read_text() == "x\n"
    assert st.pid_file.exists() and st.log_file.exists()


def test_a_runner_whose_run_was_replaced_writes_no_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = state(tmp_path)
    record = {"head": "abc", "commands": ["true"], "workdir": str(tmp_path), "timeout_seconds": 60, "started_at": 1.0}
    st.run_file.write_text(json.dumps(record))
    real = checks.card_done

    def replaced_while_running(commands: tuple[str, ...], workdir: Path, timeout_seconds: int) -> checks.CheckResult:
        st.run_file.write_text(json.dumps({**record, "started_at": 2.0}))
        return real(commands, workdir, timeout_seconds)

    monkeypatch.setattr(checks, "card_done", replaced_while_running)
    assert donewhen.run_detached(st.root) == 0
    assert not st.result_file.exists()


def test_a_runner_without_a_readable_record_fails(tmp_path: Path) -> None:
    st = state(tmp_path)
    assert donewhen.run_detached(st.root) == 1
    st.run_file.write_text(json.dumps({"head": "abc", "commands": "true"}))
    assert donewhen.run_detached(st.root) == 1


def test_the_scope_launcher_is_used_only_where_systemd_run_works() -> None:
    probed: list[list[str]] = []

    def probe_ok(argv: list[str]) -> bool:
        probed.append(argv)
        return True

    prefix = donewhen.scope_launcher(lambda name: f"/bin/{name}", probe_ok)
    assert prefix[:3] == ("/bin/systemd-run", "--user", "--scope")
    assert probed == [[*prefix, "true"]]
    assert donewhen.scope_launcher(lambda name: None, probe_ok) == ()
    assert donewhen.scope_launcher(lambda name: f"/bin/{name}", lambda argv: False) == ()


def test_a_scoped_runner_leaves_the_callers_cgroup(tmp_path: Path) -> None:
    if not donewhen.scope_launcher(shutil.which, donewhen._probe):
        pytest.skip("no user systemd manager here")
    st = state(tmp_path)
    out = tmp_path / "cgroup"
    waited = donewhen.await_result(st, spec(tmp_path, commands=(f"cat /proc/self/cgroup > {out}",)), 30)
    assert isinstance(waited, Ok) and waited.value is not None and waited.value.passed
    assert out.read_text() != Path("/proc/self/cgroup").read_text()
