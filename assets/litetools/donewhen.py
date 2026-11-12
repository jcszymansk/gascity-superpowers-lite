"""Run a card's ``done_when`` commands in a process that outlives the reviewer's session.

A card's ``done_when`` can take longer than an agent's shell tool waits (a
Gradle build and its device tests take most of an hour). The tool then moves
the command to the background and the agent ends its turn to wait. gc 1.5.1
treats a pool session idle at its prompt while it holds a claimed step as
stalled and drains it after 90 seconds, and the drain kills whatever the
session started. The next session claimed the step again and started the
checks again, and so on for as long as anyone let it.

So the checks run in a detached runner, double-forked into its own session,
and record their state next to the attempt. Leaving the session is not
enough where tmux starts each pane in its own systemd scope: stopping the
session stops the scope, and systemd kills every process in it. Where a user
systemd manager answers, the runner is started through ``systemd-run --user
--scope``, which moves it into a scope of its own.

    <attempt dir>/checks/
        run.json      what is being checked: commit, commands, workdir, timeout
        runner.pid    the runner's pid, written by the runner itself
        runner.log    the runner's own log
        result.json   the outcome, written atomically when every command ran

``verify`` attaches to a run for the same commit and commands, whichever
session started it, and starts one only when there is none or the last one
died without a result.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from litetools import checks
from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

STARTING_GRACE_SECONDS = 60
"""How long a run with no pid file yet counts as starting rather than dead."""

FIRST_POLL_SECONDS = 0.05
MAX_POLL_SECONDS = 2.0
"""Polls start short, for quick commands, and back off to this."""

_LITE_PY = Path(__file__).resolve().parent.parent / "lite.py"


@dataclass(frozen=True, slots=True)
class Spec:
    """What one run checks.

    Attributes:
        head: The attempt commit the commands run against.
        commands: The card's ``done_when`` commands, in order.
        workdir: The item worktree they run in.
        timeout_seconds: The limit for each command.
    """

    head: str
    commands: tuple[str, ...]
    workdir: Path
    timeout_seconds: int

    def matches(self, data: object) -> bool:
        """Return True when a stored record describes this same run."""
        return (
            isinstance(data, dict)
            and data.get("head") == self.head
            and data.get("commands") == list(self.commands)
        )


@dataclass(frozen=True, slots=True)
class State:
    """The files of one attempt's checks run.

    Attributes:
        root: ``<attempt dir>/checks``.
    """

    root: Path

    @property
    def run_file(self) -> Path:
        """What the run checks; its presence means a run was started."""
        return self.root / "run.json"

    @property
    def pid_file(self) -> Path:
        """The detached runner's pid."""
        return self.root / "runner.pid"

    @property
    def log_file(self) -> Path:
        """The runner's own output."""
        return self.root / "runner.log"

    @property
    def result_file(self) -> Path:
        """The finished run's outcome."""
        return self.root / "result.json"


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_atomic(path: Path, data: object) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def outcomes(state: State, spec: Spec) -> tuple[checks.CommandOutcome, ...] | None:
    """Return how each command of this finished run ended, or None when it has not finished."""
    data = _load(state.result_file)
    if not spec.matches(data) or not isinstance(data, dict):
        return None
    raw = data.get("outcomes")
    if not isinstance(raw, list) or len(raw) != len(spec.commands):
        log.warning("checks result %s is malformed; it will be run again", state.result_file)
        return None
    parsed: list[checks.CommandOutcome] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None
        command, code, output = entry.get("command"), entry.get("exit_code"), entry.get("output")
        if not isinstance(command, str) or not (code is None or isinstance(code, int)) or not isinstance(output, str):
            log.warning("checks result %s is malformed; it will be run again", state.result_file)
            return None
        parsed.append(checks.CommandOutcome(command, code, output))
    return tuple(parsed)


def result(state: State, spec: Spec) -> checks.CheckResult | None:
    """Return the card-done check of this finished run, or None when it has not finished."""
    finished = outcomes(state, spec)
    return None if finished is None else checks.card_done_from(finished, spec.timeout_seconds)


def forget(state: State) -> None:
    """Drop the run's record and result, so the next request starts a new run."""
    for path in (state.result_file, state.run_file, state.pid_file):
        path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running(state: State, spec: Spec, now: float) -> bool:
    """Return True while a runner for this run is starting or alive."""
    if not spec.matches(_load(state.run_file)):
        return False
    try:
        pid = int(state.pid_file.read_text().strip())
    except (OSError, ValueError):
        try:
            started = state.run_file.stat().st_mtime
        except OSError:
            return False
        return now - started < STARTING_GRACE_SECONDS
    return _pid_alive(pid)


def start(state: State, spec: Spec) -> Result[None, str]:
    """Start a detached runner for ``spec``, replacing any dead or different run."""
    try:
        state.root.mkdir(parents=True, exist_ok=True)
        for stale in (state.result_file, state.pid_file):
            stale.unlink(missing_ok=True)
        _write_atomic(
            state.run_file,
            {
                "head": spec.head,
                "commands": list(spec.commands),
                "workdir": str(spec.workdir),
                "timeout_seconds": spec.timeout_seconds,
                "started_at": time.time(),
            },
        )
    except OSError as error:
        return Err(f"could not record the checks run in {state.root}: {error}")
    launcher = scope_launcher(shutil.which, _probe)
    log.info("starting the done_when runner for %s in %s (scope: %s)", spec.head, spec.workdir, bool(launcher))
    child = os.fork()
    if child == 0:
        _detach_and_exec(state, spec.workdir, launcher)
    os.waitpid(child, 0)
    return Ok(None)


def _detach_and_exec(state: State, workdir: Path, launcher: tuple[str, ...]) -> None:
    """In the forked child: leave the session, fork again and exec the runner.

    The second fork makes the runner an orphan at once, so it belongs to no
    agent's process tree; ``launcher`` moves it out of the agent's cgroup.
    """
    try:
        os.setsid()
        if os.fork() != 0:
            os._exit(0)
        os.chdir(workdir)
        devnull = os.open(os.devnull, os.O_RDONLY)
        out = os.open(state.log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(devnull, 0)
        os.dup2(out, 1)
        os.dup2(out, 2)
        argv = [*launcher, sys.executable, str(_LITE_PY), "done-when-run", str(state.root)]
        os.execv(argv[0], argv)
    finally:
        os._exit(127)


def run_detached(root: Path) -> int:
    """The runner's body: run every command in ``run.json`` and write ``result.json``."""
    state = State(root)
    data = _load(state.run_file)
    if not isinstance(data, dict):
        print(f"done-when-run: no readable run record in {state.run_file}", file=sys.stderr)
        return 1
    commands = data.get("commands")
    workdir = data.get("workdir")
    timeout_seconds = data.get("timeout_seconds")
    if (
        not isinstance(commands, list)
        or not all(isinstance(c, str) for c in commands)
        or not isinstance(workdir, str)
        or not isinstance(timeout_seconds, int)
    ):
        print(f"done-when-run: malformed run record {state.run_file}", file=sys.stderr)
        return 1
    state.pid_file.write_text(f"{os.getpid()}\n")
    ran = [checks.run_command(c, Path(workdir), timeout_seconds) for c in commands]
    current = _load(state.run_file)
    if not isinstance(current, dict) or current.get("started_at") != data.get("started_at"):
        log.info("the run in %s was replaced while this runner worked; its result is dropped", root)
        return 0
    _write_atomic(
        state.result_file,
        {
            "head": data.get("head"),
            "commands": commands,
            "outcomes": [{"command": o.command, "exit_code": o.exit_code, "output": o.output} for o in ran],
            "finished_at": time.time(),
        },
    )
    print(f"done-when-run: finished, {'passed' if all(o.passed for o in ran) else 'failed'}", flush=True)
    return 0


SCOPE_PROBE_TIMEOUT_SECONDS = 10


def scope_launcher(which: Callable[[str], str | None], probe: Callable[[list[str]], bool]) -> tuple[str, ...]:
    """Return the command prefix that starts the runner in a systemd scope of its own.

    Args:
        which: Finds a program on PATH (``shutil.which``).
        probe: Runs a command and reports whether it succeeded.

    Returns:
        The ``systemd-run`` prefix when a user manager can create scopes,
        otherwise nothing, and the runner shares the caller's cgroup.
    """
    binary = which("systemd-run")
    if binary is None:
        log.info("no systemd-run on PATH; the done_when runner stays in this cgroup")
        return ()
    prefix = (binary, "--user", "--scope", "--quiet", "--collect", "--description=superpowers-lite done_when")
    if not probe([*prefix, "true"]):
        log.warning("systemd-run cannot create a user scope here; the done_when runner stays in this cgroup")
        return ()
    return prefix


def _probe(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, capture_output=True, timeout=SCOPE_PROBE_TIMEOUT_SECONDS, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def await_outcomes(
    state: State, spec: Spec, budget_seconds: float
) -> Result[tuple[checks.CommandOutcome, ...] | None, str]:
    """Attach to this run, starting it if needed, and wait up to ``budget_seconds``.

    Returns:
        How each command ended when the run finished in time, None while it still runs.
    """
    deadline = time.monotonic() + budget_seconds
    poll = FIRST_POLL_SECONDS
    while True:
        finished = outcomes(state, spec)
        if finished is not None:
            return Ok(finished)
        if not running(state, spec, time.time()):
            started = start(state, spec)
            if isinstance(started, Err):
                return started
        if time.monotonic() >= deadline:
            return Ok(None)
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
        poll = min(poll * 2, MAX_POLL_SECONDS)


def await_result(state: State, spec: Spec, budget_seconds: float) -> Result[checks.CheckResult | None, str]:
    """``await_outcomes`` as the card-done check."""
    waited = await_outcomes(state, spec, budget_seconds)
    if isinstance(waited, Err):
        return waited
    return Ok(None if waited.value is None else checks.card_done_from(waited.value, spec.timeout_seconds))
