"""End-to-end tests of the pack commands against a fake gc and real git."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from litetools import card as cards
from litetools import commands
from litetools.ladder import Tier, first_attempt
from litetools.result import Ok

PACK = Path(__file__).resolve().parents[2]
FAKE_GC = Path(__file__).resolve().parent / "fake_gc.py"
ANCHOR, CONVOY, PARENT, ROOT = "st-1", "st-cv-1", "st-cv-0", "st-wf-1"
ME = "lite-session-1"

CARD = """+++
schema = "lite.card.v1"
id = "st-1"
kind = "bugfix"
files = ["src/app.txt", "tests/app_test.txt"]
done_when = ["grep -q fixed src/app.txt"]
+++

## Goal

The app prints fixed.

## Interfaces

None.

## Context

src/app.txt:1 holds broken.

## Steps

1. Replace broken with fixed.

## Out of scope

Everything else.
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@dataclass
class World:
    """A city, a rig repository, a fake bead store and a way to run commands."""

    tmp: Path
    city: Path
    rig: Path
    state_path: Path

    @property
    def state(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.state_path.read_text())
        return data

    def save(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state))

    def bead(self, bead_id: str) -> dict[str, Any]:
        bead: dict[str, Any] = self.state["beads"][bead_id]
        return bead

    def meta(self, bead_id: str) -> dict[str, str]:
        meta: dict[str, str] = self.bead(bead_id).get("metadata", {})
        return meta

    def add_step(self, bead_id: str, step: str, tier: str = "", issue_type: str = "task", round_: str = "") -> None:
        state = self.state
        meta = {"gc.root_bead_id": ROOT, "lite.step": step}
        if tier:
            meta["lite.tier"] = tier
        if round_:
            meta["lite.round"] = round_
        state["beads"][bead_id] = {"id": bead_id, "status": "open", "title": f"{step} {tier}", "description": f"Run `gc superpowers-lite {step}`.", "assignee": "", "issue_type": issue_type, "metadata": meta}
        state["claim_queue"] = [bead_id]
        self.save(state)

    def run(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        base = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp),
            "GC_CITY": str(self.city),
            "GC_RIG": "st",
            "GC_RIG_ROOT": str(self.rig),
            "GC_SESSION_ID": ME,
            "GC_PACK_DIR": str(PACK),
            "FAKE_GC_STATE": str(self.state_path),
            "LITE_GC_BIN": str(FAKE_GC),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        }
        return subprocess.run([sys.executable, str(PACK / "assets" / "lite.py"), *args], env={**base, **(env or {})}, capture_output=True, text=True, check=False)

    def claim_and_run(
        self, bead_id: str, step: str, *args: str, tier: str = "", round_: str = "", env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.add_step(bead_id, step, tier, round_=round_)
        claimed = self.run("claim", env=env)
        assert claimed.returncode == 0, claimed.stderr
        return self.run(*args, env=env)

    @property
    def worktree(self) -> Path:
        return self.city / ".gc" / "worktrees" / "st" / ANCHOR

    @property
    def artifacts(self) -> Path:
        return self.city / ".gc" / "artifacts" / "st" / "superpowers-lite" / ANCHOR

    def card_dir(self, number: int = 1) -> Path:
        return self.artifacts / "cards" / str(number)

    def draft(self, number: int = 1) -> Path:
        path = self.artifacts / "drafts" / f"{number}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@pytest.fixture
def world(tmp_path: Path) -> World:
    os.chmod(FAKE_GC, 0o755)
    rig = tmp_path / "rig"
    rig.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    os.environ.update(env)
    git(rig, "init", "-q", "-b", "main")
    (rig / "src").mkdir()
    (rig / "tests").mkdir()
    (rig / "src" / "app.txt").write_text("broken\n")
    (rig / "tests" / "app_test.txt").write_text("#[test]\nfn works() {}\n")
    (rig / ".gitignore").write_text("build/\n")
    git(rig, "add", "-A")
    git(rig, "commit", "-q", "-m", "init")
    city = tmp_path / "city"
    city.mkdir()
    beads = {
        ANCHOR: {"id": ANCHOR, "status": "open", "title": "fix the app", "description": "It prints broken.", "assignee": "", "metadata": {}},
        CONVOY: {"id": CONVOY, "status": "open", "title": "unit", "description": "", "assignee": "", "metadata": {"gc.synthetic_kind": "drain-unit-convoy", "gc.drain_member_id": ANCHOR, "gc.parent_convoy_id": PARENT}},
        PARENT: {"id": PARENT, "status": "open", "title": "convoy", "description": "", "assignee": "", "metadata": {}},
        ROOT: {"id": ROOT, "status": "open", "title": "item", "description": "", "assignee": "", "metadata": {"gc.kind": "workflow", "gc.input_convoy_id": CONVOY}},
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"beads": beads, "me": ME, "rigs": [{"name": "st", "default_branch": "main"}]}))
    return World(tmp_path, city, rig, state_path)


def prepared(world: World) -> None:
    result = world.claim_and_run("s-prep", "prepare-worktree", "prepare-worktree")
    assert result.returncode == 0, result.stderr


def sealed(world: World, card: str = CARD) -> None:
    prepared(world)
    world.draft().write_text(card)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 0, result.stderr


def attempted(
    world: World, tier: str, content: str, extra: dict[str, str] | None = None, round_: str = "", name: str = ""
) -> None:
    started = world.claim_and_run(name or f"s-att-{tier}{round_}", "attempt", "attempt-start", tier=tier, round_=round_)
    assert started.returncode == 0, started.stderr
    (world.worktree / "src" / "app.txt").write_text(content)
    for name, text in (extra or {}).items():
        (world.worktree / name).parent.mkdir(parents=True, exist_ok=True)
        (world.worktree / name).write_text(text)
    finished = world.run("attempt-finish", "--summary", f"{tier} change")
    assert finished.returncode == 0, finished.stderr


def verified(world: World, tier: str, round_: str = "", name: str = "") -> subprocess.CompletedProcess[str]:
    return world.claim_and_run(name or f"s-ver-{tier}{round_}", "verify", "verify", tier=tier, round_=round_)


def output(world: World, step: str) -> Any:
    return json.loads(world.meta(step)["gc.output_json"])


# --- prepare-worktree ----------------------------------------------------------


def test_prepare_worktree_creates_the_worktree_and_records_it(world: World) -> None:
    prepared(world)
    meta = world.meta(ANCHOR)
    base = git(world.rig, "rev-parse", "main")
    assert meta["work_dir"] == str(world.worktree)
    assert meta["target"] == f"lite/{ANCHOR}"
    assert meta["lite.base_commit"] == base
    assert meta["lite.artifact_dir"] == str(world.artifacts)
    assert world.meta(ROOT)["lite.anchor_id"] == ANCHOR
    assert git(world.worktree, "rev-parse", "HEAD") == base
    assert world.bead("s-prep")["status"] == "closed"
    assert world.meta("s-prep")["gc.outcome"] == "pass"
    assert world.state["drained"] == 1


def test_prepare_worktree_uses_the_parent_convoy_target_and_refuses_the_default_branch(world: World) -> None:
    state = world.state
    state["beads"][PARENT]["metadata"]["target"] = "main"
    world.save(state)
    result = world.claim_and_run("s-prep", "prepare-worktree", "prepare-worktree")
    assert result.returncode == 0
    assert world.meta("s-prep")["gc.outcome"] == "fail"
    assert "only a human merges into it" in world.bead("s-prep")["close_reason"]


def test_verify_closes_failed_when_the_checks_cannot_run(world: World) -> None:
    prepared(world)
    result = verified(world, "t1")
    assert result.returncode == 0
    assert world.meta("s-ver-t1")["gc.outcome"] == "fail"
    assert "could not read" in world.bead("s-ver-t1")["close_reason"]


def _blocked_by(world: World, *blockers: dict[str, Any]) -> None:
    state = world.state
    state["beads"][ANCHOR]["dependencies"] = [
        {"id": "st-0", "dependency_type": "parent-child", "status": "open", "metadata": {}},
        *({"dependency_type": "blocks", "metadata": {}, **b} for b in blockers),
    ]
    world.save(state)


@pytest.mark.parametrize(
    "blocker",
    [
        {"id": "st-p", "status": "closed", "metadata": {"lite.result": "landed"}},
        {"id": "st-p", "status": "closed"},
    ],
    ids=["landed", "closed-by-a-human"],
)
def test_prepare_worktree_proceeds_when_every_predecessor_is_done(world: World, blocker: dict[str, Any]) -> None:
    _blocked_by(world, blocker)
    prepared(world)
    assert world.meta("s-prep")["gc.outcome"] == "pass"
    assert world.worktree.exists()


@pytest.mark.parametrize(
    ("blocker", "shown"),
    [
        ({"id": "st-p", "status": "open", "metadata": {"lite.result": "uncuttable"}}, "st-p (open, lite.result=uncuttable)"),
        ({"id": "st-p", "status": "open"}, "st-p (open, lite.result=none)"),
        ({"id": "st-p", "status": "in_progress", "metadata": {"lite.result": "landed"}}, "st-p (in_progress, lite.result=landed)"),
        ({"id": "st-p", "status": "closed", "metadata": {"lite.result": "blocked"}}, "st-p (closed, lite.result=blocked)"),
    ],
    ids=["failed-item", "never-ran", "not-closed", "closed-without-landing"],
)
def test_prepare_worktree_skips_an_item_whose_predecessor_did_not_land(
    world: World, blocker: dict[str, Any], shown: str
) -> None:
    _blocked_by(world, {"id": "st-q", "status": "closed", "metadata": {"lite.result": "landed"}}, blocker)
    result = world.claim_and_run("s-prep", "prepare-worktree", "prepare-worktree")
    assert result.returncode == 0
    assert world.meta("s-prep")["gc.outcome"] == "fail"
    reason = world.bead("s-prep")["close_reason"]
    assert reason.startswith(f"skipped: {ANCHOR} is blocked by work that did not land")
    assert shown in reason
    assert "st-q" not in reason
    assert world.meta(ANCHOR)["lite.result"] == "skipped"
    assert "work_dir" not in world.meta(ANCHOR)
    assert not world.worktree.exists()


FILE_PROTOCOL = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}


def _with_submodule(world: World) -> None:
    lib = world.tmp / "lib-src"
    lib.mkdir()
    git(lib, "init", "-q", "-b", "main")
    (lib / "lib.txt").write_text("from the submodule\n")
    git(lib, "add", "-A")
    git(lib, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "lib")
    git(world.rig, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "lib")
    git(world.rig, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add lib")


def test_prepare_worktree_checks_out_submodules(world: World) -> None:
    _with_submodule(world)
    result = world.claim_and_run("s-prep", "prepare-worktree", "prepare-worktree", env=FILE_PROTOCOL)
    assert result.returncode == 0, result.stderr
    assert world.meta("s-prep")["gc.outcome"] == "pass"
    assert (world.worktree / "lib" / "lib.txt").read_text() == "from the submodule\n"


def test_prepare_worktree_fails_when_a_submodule_cannot_be_checked_out(world: World) -> None:
    _with_submodule(world)
    missing = "0123456789abcdef0123456789abcdef01234567"
    git(world.rig, "update-index", "--cacheinfo", f"160000,{missing},lib")
    git(world.rig, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "point lib at a missing commit")
    result = world.claim_and_run("s-prep", "prepare-worktree", "prepare-worktree", env=FILE_PROTOCOL)
    assert result.returncode == 0
    assert world.meta("s-prep")["gc.outcome"] == "fail"
    assert "could not check out submodules" in world.bead("s-prep")["close_reason"]


def test_prepare_worktree_bases_on_an_existing_target(world: World) -> None:
    git(world.rig, "branch", "feature/x")
    git(world.rig, "commit", "-q", "--allow-empty", "-m", "later on main")
    state = world.state
    state["beads"][ANCHOR]["metadata"]["target"] = "feature/x"
    world.save(state)
    prepared(world)
    assert world.meta(ANCHOR)["lite.base_commit"] == git(world.rig, "rev-parse", "feature/x")


# --- claim -------------------------------------------------------------------------


def test_claim_prints_the_step_and_records_it(world: World) -> None:
    world.add_step("s-x", "verify", "t1")
    result = world.run("claim")
    assert result.returncode == 0
    assert "Claimed step s-x" in result.stdout and "Run `gc superpowers-lite verify`" in result.stdout
    claims = world.city / ".gc" / "runtime" / "superpowers-lite" / "claims" / f"{ME}.json"
    assert json.loads(claims.read_text()) == {"bead_id": "s-x"}


def test_claim_with_no_work_says_drained(world: World) -> None:
    result = world.run("claim")
    assert result.returncode == 0 and "you are drained" in result.stdout


def test_claim_releases_a_drain_item_root_instead_of_working_it(world: World) -> None:
    state = world.state
    state["beads"]["wf-root"] = {"id": "wf-root", "status": "open", "title": "root", "description": "", "assignee": "", "metadata": {"gc.kind": "workflow"}}
    state["claim_queue"] = ["wf-root"]
    world.save(state)
    result = world.run("claim")
    assert result.returncode == 0 and "drain item root" in result.stdout
    root = world.bead("wf-root")
    assert root["assignee"] == "" and root["status"] != "closed"
    assert root["metadata"] == {"gc.kind": "workflow"}
    assert world.state["drained"] == 1


def test_claim_refuses_a_bead_routed_elsewhere(world: World) -> None:
    world.add_step("s-x", "verify", "t1")
    state = world.state
    state["beads"]["s-x"]["metadata"]["gc.routed_to"] = "other.agent"
    world.save(state)
    result = world.run("claim", env={"GC_TEMPLATE": "st/superpowers-lite.card-reviewer"})
    assert result.returncode == 1 and "routed to other.agent" in result.stderr


def test_commands_refuse_a_step_of_another_kind(world: World) -> None:
    result = world.claim_and_run("s-x", "land", "verify")
    assert result.returncode == 1
    assert "is a 'land' step; this command handles 'verify' steps" in result.stderr


def test_commands_need_a_claim(world: World) -> None:
    result = world.run("verify")
    assert result.returncode == 1 and "run `gc superpowers-lite claim` first" in result.stderr


def test_missing_environment_is_refused(world: World) -> None:
    result = world.run("claim", env={"GC_RIG_ROOT": ""})
    assert result.returncode == 1 and "missing environment: GC_RIG_ROOT" in result.stderr


# --- cut-card ----------------------------------------------------------------------


def test_cut_card_start_prints_the_bead_and_template(world: World) -> None:
    prepared(world)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-start")
    assert result.returncode == 0, result.stderr
    assert "fix the app" in result.stdout and "It prints broken." in result.stdout
    assert str(world.artifacts / "drafts" / "1.md") in result.stdout
    assert 'id = "st-1"' in result.stdout
    assert "Example card, from another project" in result.stdout and 'id = "ex-41"' in result.stdout


def test_cut_card_finish_lists_every_error_and_keeps_the_step_open(world: World) -> None:
    prepared(world)
    world.draft().write_text(CARD.replace('kind = "bugfix"', 'kind = "nope"').replace("## Goal", "## Goals"))
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1
    assert "'kind' must be one of" in result.stderr and "missing section '## Goal'" in result.stderr
    assert world.bead("s-cut")["status"] == "in_progress"


def test_cut_card_finish_refuses_a_card_for_another_bead(world: World) -> None:
    prepared(world)
    world.draft().write_text(CARD.replace('id = "st-1"', 'id = "st-9"'))
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "must be st-1" in result.stderr


def test_cut_card_finish_seals_the_card_with_the_kind_checklist(world: World) -> None:
    sealed(world)
    text = (world.card_dir() / "card.md").read_text()
    checklist = (PACK / "assets" / "kinds" / "bugfix.md").read_text().strip()
    assert text.rstrip().endswith(checklist)
    assert world.meta(ANCHOR)["lite.kind"] == "bugfix"
    assert world.meta("s-cut")["gc.outcome"] == "pass"


def test_cut_card_finish_refuses_a_solution_in_steps(world: World) -> None:
    prepared(world)
    world.draft().write_text(CARD.replace("## Steps\n", "## Steps\n\n```\nnew code\n```\n"))
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "'## Steps' holds a code block" in result.stderr
    assert world.bead("s-cut")["status"] == "in_progress"


def _card_quoting(world: World, code: str) -> None:
    world.draft().write_text(CARD.replace("## Context\n", f"## Context\n\n```\n{code}\n```\n"))


def test_cut_card_finish_refuses_context_code_not_in_the_repository(world: World) -> None:
    prepared(world)
    _card_quoting(world, "made up line")
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "must quote the repository exactly" in result.stderr
    assert world.bead("s-cut")["status"] == "in_progress"


def test_cut_card_finish_accepts_context_code_from_the_repository(world: World) -> None:
    prepared(world)
    tracked = next(path for path in world.worktree.iterdir() if path.is_file())
    line = next(text for text in tracked.read_text().splitlines() if text.strip())
    _card_quoting(world, line)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 0, result.stderr


def test_cut_card_finish_refuses_a_worktree_the_cutter_changed(world: World) -> None:
    prepared(world)
    (world.worktree / "written_by_the_cutter.txt").write_text("made up line\n")
    _card_quoting(world, "made up line")
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "the cutter must change nothing" in result.stderr


def test_cut_card_blocked_fails_the_item(world: World) -> None:
    prepared(world)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish", "--blocked", "the bead names no bug")
    assert result.returncode == 0
    assert world.meta("s-cut")["gc.outcome"] == "fail"
    assert world.meta(ANCHOR)["lite.result"] == "uncuttable"


# --- attempts, verify and verdict --------------------------------------------------


def test_a_restarted_session_resumes_the_attempt_without_a_reset(world: World) -> None:
    sealed(world)
    first = world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    assert first.returncode == 0, first.stderr
    assert "already started" not in first.stdout
    assert world.meta("s-att-t1")["lite.attempt_started"] == "true"
    (world.worktree / "src" / "app.txt").write_text("half done\n")
    again = world.run("attempt-start")
    assert again.returncode == 0, again.stderr
    assert "already started by a session that was restarted" in again.stdout
    assert (world.worktree / "src" / "app.txt").read_text() == "half done\n"


def test_run_reports_the_exit_status_and_output_from_the_worktree(world: World) -> None:
    sealed(world)
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    failed = world.run("run", "pwd && exit 3")
    assert failed.returncode == 0, failed.stderr
    assert failed.stdout.startswith("Exit 3 (failed): pwd && exit 3")
    assert str(world.worktree) in failed.stdout
    passed = world.run("run", "echo fine")
    assert passed.stdout.startswith("Exit 0 (passed): echo fine") and "fine" in passed.stdout


def test_run_attaches_to_a_running_command_and_reports_it_once(world: World) -> None:
    sealed(world)
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    counter = world.tmp / "run_count"
    command = f"sleep 2 && echo ran >> {counter} && echo done"
    first = world.run("run", command, env=SHORT_WAIT)
    assert first.returncode == 0, first.stderr
    assert first.stdout.startswith("Still running") and "Do not end your turn" in first.stdout
    second = world.run("run", command)
    assert second.stdout.startswith("Exit 0 (passed)") and "done" in second.stdout
    assert counter.read_text().splitlines() == ["ran"]
    world.run("run", command)
    assert counter.read_text().splitlines() == ["ran", "ran"]


def test_run_needs_a_claimed_attempt_and_a_command(world: World) -> None:
    sealed(world)
    unclaimed = world.run("run", "true")
    assert unclaimed.returncode == 1
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    empty = world.run("run", "  ")
    assert empty.returncode == 1 and "run needs a command" in empty.stderr


def test_attempt_finish_commits_and_reports(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n")
    base = world.meta(ANCHOR)["lite.base_commit"]
    head = git(world.worktree, "rev-parse", "HEAD")
    assert head != base
    assert git(world.worktree, "log", "-1", "--format=%s") == "st-1 (t1): t1 change"
    report = (world.card_dir() / "attempts" / "t1" / "report.md").read_text()
    assert 'status = "done"' in report and f'commit = "{head}"' in report
    assert world.meta("s-att-t1")["lite.attempt_status"] == "done"


def test_attempt_commit_carries_the_bead_trailer_and_a_short_subject(world: World) -> None:
    sealed(world)
    assert world.claim_and_run("s-att", "attempt", "attempt-start", tier="t1").returncode == 0
    (world.worktree / "src" / "app.txt").write_text("fixed\n")
    summary = "x" * 100 + "\nsecond line"
    assert world.run("attempt-finish", "--summary", summary).returncode == 0
    subject = git(world.worktree, "log", "-1", "--format=%s")
    assert subject.startswith("st-1 (t1): x") and len(subject) == 72
    assert git(world.worktree, "log", "-1", "--format=%(trailers:key=Bead,valueonly)") == ANCHOR
    assert summary in git(world.worktree, "log", "-1", "--format=%b")


@pytest.mark.parametrize(
    ("summary", "subject"),
    [
        ("Fixed it. Then more detail.", "st-1 (t1): Fixed it"),
        ("v1.2 parser fixed", "st-1 (t1): v1.2 parser fixed"),
        ("word " * 30, "st-1 (t1): " + " ".join(["word"] * 12)),
    ],
)
def test_attempt_subject_is_the_first_sentence_cut_at_a_word(summary: str, subject: str) -> None:
    message = commands._attempt_message("st-1", first_attempt(Tier.T1).key, summary)
    assert message.splitlines()[0] == subject
    assert len(subject) <= 72


def test_attempt_finish_needs_exactly_one_of_summary_or_blocked(world: World) -> None:
    sealed(world)
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    assert world.run("attempt-finish").returncode == 1
    assert world.run("attempt-finish", "--summary", "a", "--blocked", "b").returncode == 1
    assert world.run("attempt-finish", "--summary", "  ").returncode == 1


def test_clean_t1_attempt_passes_checks_and_approval_lands(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n")
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert "Every check passed" in result.stdout
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert world.meta(ANCHOR)["lite.card_overlap.t1"] == "0/0"
    assert (world.card_dir() / "attempts" / "t1" / "attempt.diff").read_text().count("+fixed") == 1
    approved = world.run("verdict", "approve")
    assert approved.returncode == 0, approved.stderr
    assert output(world, "s-ver-t1") == {"next": [{"action": "land", "round": "1"}]}
    assert world.meta("s-ver-t1")["gc.outcome"] == "pass"
    assert world.meta(ANCHOR)["lite.passed_tier"] == "t1"
    assert world.meta(ANCHOR)["lite.attempt.t1"] == "approved"


def test_verify_records_lines_copied_from_the_card(world: World) -> None:
    sealed(world, CARD.replace("1. Replace broken with fixed.", "1. Replace broken with fixed.\n2. Add this line after it:\n\nthe app is fixed now"))
    attempted(world, "t1", "fixed\nthe app is fixed now\nsomething the executor wrote\n")
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert world.meta(ANCHOR)["lite.card_overlap.t1"] == "1/2"


SHORT_WAIT = {"LITE_VERIFY_WAIT_SECONDS": "0.2"}


def slow_card(world: World, before: str) -> str:
    """A card whose done_when first runs ``before``, sleeps, then counts its runs."""
    counter = world.tmp / "done_when_runs"
    command = f"{before}sleep 2 && echo ran >> {counter} && grep -q fixed src/app.txt"
    return CARD.replace('done_when = ["grep -q fixed src/app.txt"]', f"done_when = [{json.dumps(command)}]")


def runs(world: World) -> int:
    counter = world.tmp / "done_when_runs"
    return len(counter.read_text().splitlines()) if counter.exists() else 0


def checks_dir(world: World, key: str = "t1") -> Path:
    return world.card_dir() / "attempts" / key / "checks"


def test_slow_done_when_leaves_the_step_open_and_a_second_verify_attaches(world: World) -> None:
    sealed(world, slow_card(world, ""))
    attempted(world, "t1", "fixed\n")
    first = world.claim_and_run("s-ver-t1", "verify", "verify", tier="t1", env=SHORT_WAIT)
    assert first.returncode == 0, first.stderr
    assert "still running" in first.stdout and "Do not end your turn" in first.stdout
    assert "gc.output_json" not in world.meta("s-ver-t1")
    assert world.meta("s-ver-t1").get("lite.checks") != "passed"
    second = world.run("verify")
    assert second.returncode == 0, second.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert "Every check passed" in second.stdout
    assert runs(world) == 1


def test_build_products_of_a_running_check_do_not_fail_worktree_clean(world: World) -> None:
    sealed(world, slow_card(world, "touch residue.txt && "))
    attempted(world, "t1", "fixed\n")
    first = world.claim_and_run("s-ver-t1", "verify", "verify", tier="t1", env=SHORT_WAIT)
    assert "still running" in first.stdout, first.stderr
    second = world.run("verify")
    assert second.returncode == 0, second.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert not (world.worktree / "residue.txt").exists()


def test_a_runner_that_died_without_a_result_is_started_again(world: World) -> None:
    sealed(world, slow_card(world, ""))
    attempted(world, "t1", "fixed\n")
    first = world.claim_and_run("s-ver-t1", "verify", "verify", tier="t1", env=SHORT_WAIT)
    assert "still running" in first.stdout, first.stderr
    pid_file = checks_dir(world) / "runner.pid"
    for _ in range(100):
        if pid_file.exists():
            break
        subprocess.run(["sleep", "0.05"], check=True)
    pid = int(pid_file.read_text())
    os.killpg(os.getpgid(pid), 9)
    second = world.run("verify")
    assert second.returncode == 0, second.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert runs(world) == 1


def test_verdict_needs_passing_checks_and_a_reason_to_reject(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n")
    world.add_step("s-ver-t1", "verify", "t1")
    assert world.run("claim").returncode == 0
    early = world.run("verdict", "approve")
    assert early.returncode == 1 and "run `gc superpowers-lite verify` first" in early.stderr
    assert world.run("verify").returncode == 0
    no_reason = world.run("verdict", "reject")
    assert no_reason.returncode == 1 and "needs --reason" in no_reason.stderr


def test_failed_checks_retry_t1_without_review(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "still broken\n", extra={"src/other.txt": "x\n"})
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert output(world, "s-ver-t1") == {"next": [{"action": "t1", "round": "2"}]}
    assert world.meta(ANCHOR)["lite.last_rejected"] == "t1"
    findings = (world.card_dir() / "attempts" / "t1" / "findings.md").read_text()
    assert "## card-done" in findings
    assert "src/other.txt" not in findings
    assert world.meta(ANCHOR)["lite.attempt.t1"] == "rejected: failed checks: card-done"


def test_an_unlisted_file_goes_to_the_reviewer_instead_of_failing_the_checks(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n", extra={"src/other.txt": "x\n"})
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert "The attempt touches files the card does not list:" in result.stdout
    assert "  - src/other.txt" in result.stdout
    assert "Accept a file only when the" in result.stdout
    assert world.meta(ANCHOR)["lite.files_touched.t1"] == "2"


def test_files_matched_by_a_card_pattern_get_no_unlisted_note(world: World) -> None:
    sealed(world, CARD.replace('files = ["src/app.txt", "tests/app_test.txt"]', 'files = ["src/**", "tests/app_test.txt"]'))
    attempted(world, "t1", "fixed\n", extra={"src/deep/other.txt": "x\n"})
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert "does not list" not in result.stdout


def test_an_empty_attempt_fails_the_non_empty_diff_check(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "broken\n")
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    findings = (world.card_dir() / "attempts" / "t1" / "findings.md").read_text()
    assert "## non-empty-diff" in findings and "the attempt changed nothing" in findings


def test_deleting_a_test_goes_to_the_reviewer_with_the_removal_listed(world: World) -> None:
    sealed(world)
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    (world.worktree / "src" / "app.txt").write_text("fixed\n")
    (world.worktree / "tests" / "app_test.txt").unlink()
    assert world.run("attempt-finish", "--summary", "drop test").returncode == 0
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert "The attempt removes tests:" in result.stdout
    assert "  - deleted test file: tests/app_test.txt" in result.stdout
    assert "Accept a removal only when the card asks for it" in result.stdout


def test_an_attempt_that_removes_no_test_gets_no_removal_note(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n")
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert "removes tests" not in result.stdout
    assert "does not list" not in result.stdout
    assert world.meta(ANCHOR)["lite.files_touched.t1"] == "1"


def test_adding_a_skip_marker_is_rejected_without_review(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n", extra={"tests/app_test.txt": "#[ignore]\n#[test]\nfn works() {}\n"})
    assert verified(world, "t1").returncode == 0
    assert "no-skip-markers" in world.meta(ANCHOR)["lite.attempt.t1"]
    findings = (world.card_dir() / "attempts" / "t1" / "findings.md").read_text()
    assert "added a skip marker in tests/app_test.txt: #[ignore]" in findings


def test_an_attempt_that_changes_nothing_is_rejected(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "broken\n")
    assert verified(world, "t1").returncode == 0
    assert output(world, "s-ver-t1") == {"next": [{"action": "t1", "round": "2"}]}


def test_a_blocked_attempt_escalates(world: World) -> None:
    sealed(world)
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    assert world.run("attempt-finish", "--blocked", "the file is generated").returncode == 0
    assert verified(world, "t1").returncode == 0
    findings = (world.card_dir() / "attempts" / "t1" / "findings.md").read_text()
    assert "the file is generated" in findings
    assert output(world, "s-ver-t1") == {"next": [{"action": "t2", "round": "1"}]}


def test_t1_retry_starts_from_the_rejected_attempt_and_sees_its_findings(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "still broken\n", extra={"src/other.txt": "x\n"})
    assert verified(world, "t1").returncode == 0
    assert world.meta(ANCHOR)["lite.attempt.t1"] == "rejected: failed checks: card-done"
    rejected = world.meta("s-att-t1")["lite.attempt_commit"]
    started = world.claim_and_run("s-att-t1-2", "attempt", "attempt-start", tier="t1", round_="2")
    assert started.returncode == 0, started.stderr
    assert git(world.worktree, "rev-parse", "HEAD") == rejected
    assert (world.worktree / "src" / "other.txt").exists()
    assert "Attempt T1.2" in started.stdout and "This is a retry" in started.stdout
    assert str(world.card_dir() / "attempts" / "t1" / "findings.md") in started.stdout


def test_an_approved_retry_lands_with_both_attempts_recorded(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "still broken\n")
    assert verified(world, "t1").returncode == 0
    attempted(world, "t1", "fixed\n", round_="2")
    result = verified(world, "t1", "2")
    assert result.returncode == 0, result.stderr
    assert "Every check passed for the t1.2 attempt" in result.stdout
    assert world.run("verdict", "approve").returncode == 0
    assert output(world, "s-ver-t12") == {"next": [{"action": "land", "round": "1"}]}
    meta = world.meta(ANCHOR)
    assert meta["lite.attempt.t1"].startswith("rejected: failed checks: card-done")
    assert meta["lite.attempt.t1.2"] == "approved" and meta["lite.passed_tier"] == "t1"
    assert "lite.card_overlap.t1.2" in meta
    assert (world.card_dir() / "attempts" / "t1.2" / "report.md").exists()
    assert git(world.worktree, "log", "-1", "--format=%s").startswith("st-1 (t1.2): ")


def test_a_rejected_retry_escalates_to_t2_from_the_base(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "still broken\n")
    assert verified(world, "t1").returncode == 0
    attempted(world, "t1", "still broken, again\n", round_="2")
    assert verified(world, "t1", "2").returncode == 0
    assert output(world, "s-ver-t12") == {"next": [{"action": "t2", "round": "1"}]}
    assert world.meta(ANCHOR)["lite.last_rejected"] == "t1.2"
    started = world.claim_and_run("s-att-t2", "attempt", "attempt-start", tier="t2")
    assert started.returncode == 0, started.stderr
    assert git(world.worktree, "rev-parse", "HEAD") == world.meta(ANCHOR)["lite.base_commit"]
    assert str(world.card_dir() / "attempts" / "t1.2" / "findings.md") in started.stdout


def test_a_retry_with_no_rejected_attempt_is_refused(world: World) -> None:
    sealed(world)
    started = world.claim_and_run("s-att-t1-2", "attempt", "attempt-start", tier="t1", round_="2")
    assert started.returncode == 1 and "needs a rejected t1 attempt" in started.stderr


def test_a_round_past_the_retries_is_refused(world: World) -> None:
    sealed(world)
    started = world.claim_and_run("s-att-t1-3", "attempt", "attempt-start", tier="t1", round_="3")
    assert started.returncode == 1 and "past the 1 retries" in started.stderr


def test_t2_starts_from_the_base_and_sees_t1_findings(world: World) -> None:
    sealed(world)
    world.claim_and_run("s-att-t1", "attempt", "attempt-start", tier="t1")
    assert world.run("attempt-finish", "--blocked", "the file is generated").returncode == 0
    assert verified(world, "t1").returncode == 0
    (world.worktree / "build").mkdir()
    (world.worktree / "build" / "cache").write_text("keep")
    (world.worktree / "junk.txt").write_text("drop")
    started = world.claim_and_run("s-att-t2", "attempt", "attempt-start", tier="t2")
    assert started.returncode == 0, started.stderr
    assert git(world.worktree, "rev-parse", "HEAD") == world.meta(ANCHOR)["lite.base_commit"]
    assert not (world.worktree / "junk.txt").exists()
    assert (world.worktree / "build" / "cache").exists()
    assert str(world.card_dir() / "attempts" / "t1" / "findings.md") in started.stdout


def test_review_rejection_at_t2_asks_a_human_for_t3(world: World) -> None:
    sealed(world)
    attempted(world, "t2", "fixed\n")
    assert verified(world, "t2").returncode == 0
    result = world.run("verdict", "reject", "--reason", "src/app.txt:1 wrong casing")
    assert result.returncode == 0, result.stderr
    assert output(world, "s-ver-t2") == {"next": [{"action": "t3", "round": "1"}]}
    mail = world.state["mail"]
    assert len(mail) == 1 and mail[0]["to"] == "human"
    assert "gc superpowers-lite approve --rig st st-1" in mail[0]["body"]
    assert "wrong casing" in (world.card_dir() / "attempts" / "t2" / "findings.md").read_text()


def test_rejection_at_t3_blocks_and_fails(world: World) -> None:
    sealed(world)
    attempted(world, "t3", "still broken\n")
    assert verified(world, "t3").returncode == 0
    assert output(world, "s-ver-t3") == {"next": []}
    assert world.meta("s-ver-t3")["gc.outcome"] == "fail"
    assert world.meta(ANCHOR)["lite.result"] == "blocked"


# --- approve, land, close -----------------------------------------------------------


def test_approve_closes_the_single_open_gate(world: World) -> None:
    state = world.state
    state["beads"][ROOT]["metadata"]["lite.anchor_id"] = ANCHOR
    state["beads"]["g-1"] = {"id": "g-1", "status": "open", "title": "gate", "description": "", "assignee": "", "issue_type": "gate", "metadata": {"gc.root_bead_id": ROOT}}
    world.save(state)
    result = world.run("approve", ANCHOR)
    assert result.returncode == 0, result.stderr
    assert world.bead("g-1")["status"] == "closed"
    assert world.bead("g-1")["metadata"]["gc.outcome"] == "pass"
    again = world.run("approve", ANCHOR)
    assert again.returncode == 1 and "found 0" in again.stderr
    assert world.state.get("drained", 0) == 0


HUMAN_SHELL = {"GC_CITY": "", "GC_RIG": "", "GC_RIG_ROOT": "", "GC_SESSION_ID": ""}


def _open_gate(world: World) -> None:
    state = world.state
    state["beads"][ROOT]["metadata"]["lite.anchor_id"] = ANCHOR
    state["beads"]["g-1"] = {"id": "g-1", "status": "open", "title": "gate", "description": "", "assignee": "", "issue_type": "gate", "metadata": {"gc.root_bead_id": ROOT}}
    world.save(state)


def test_approve_runs_from_a_human_shell_with_an_explicit_rig(world: World) -> None:
    _open_gate(world)
    result = world.run("approve", "--rig", "st", ANCHOR, env=HUMAN_SHELL)
    assert result.returncode == 0, result.stderr
    assert world.bead("g-1")["status"] == "closed"


def test_approve_refuses_another_rig(world: World) -> None:
    _open_gate(world)
    result = world.run("approve", "--rig", "elsewhere", ANCHOR, env=HUMAN_SHELL)
    assert result.returncode == 1 and "unknown rig elsewhere" in result.stderr
    assert world.bead("g-1")["status"] == "open"


def test_approve_refuses_two_open_gates(world: World) -> None:
    _open_gate(world)
    state = world.state
    state["beads"]["g-2"] = {**state["beads"]["g-1"], "id": "g-2"}
    world.save(state)
    result = world.run("approve", ANCHOR)
    assert result.returncode == 1 and "found 2" in result.stderr
    assert world.bead("g-1")["status"] == "open" and world.bead("g-2")["status"] == "open"


def test_every_bd_call_names_the_rig(world: World) -> None:
    sealed(world)
    bd_calls = [call for call in world.state["calls"] if call[:1] == ["bd"]]
    assert bd_calls and all(call[1:3] == ["--rig", "st"] for call in bd_calls)


def test_approval_step_closes_pass(world: World) -> None:
    result = world.claim_and_run("s-appr", "approval", "approval")
    assert result.returncode == 0
    assert world.meta("s-appr")["gc.outcome"] == "pass"


def test_land_and_close_anchor(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n")
    assert verified(world, "t1").returncode == 0
    assert world.run("verdict", "approve").returncode == 0
    landed = world.claim_and_run("s-land", "land", "land")
    assert landed.returncode == 0, landed.stderr
    head = git(world.worktree, "rev-parse", "HEAD")
    assert git(world.rig, "rev-parse", f"refs/heads/lite/{ANCHOR}") == head
    assert world.meta(ANCHOR)["lite.landed_commit"] == head
    assert world.meta(ANCHOR)["lite.result"] == "landed"
    closed = world.claim_and_run("s-close", "close-anchor", "close-anchor")
    assert closed.returncode == 0, closed.stderr
    assert world.bead(ANCHOR)["status"] == "closed"
    assert world.meta("s-close")["gc.outcome"] == "pass"


def test_verify_restores_the_worktree_that_done_when_dirtied_so_land_succeeds(world: World) -> None:
    messy = "grep -q fixed src/app.txt && mkdir -p cache build && touch cache/residue build/kept && echo noise >> tests/app_test.txt"
    sealed(world, CARD.replace('done_when = ["grep -q fixed src/app.txt"]', f"done_when = [{json.dumps(messy)}]"))
    attempted(world, "t1", "fixed\n")
    commit = world.meta("s-att-t1")["lite.attempt_commit"]
    result = verified(world, "t1")
    assert result.returncode == 0, result.stderr
    assert world.meta("s-ver-t1")["lite.checks"] == "passed"
    assert git(world.worktree, "rev-parse", "HEAD") == commit
    assert git(world.worktree, "status", "--porcelain") == ""
    assert not (world.worktree / "cache").exists()
    assert (world.worktree / "build" / "kept").exists()
    assert world.run("verdict", "approve").returncode == 0
    landed = world.claim_and_run("s-land", "land", "land")
    assert landed.returncode == 0, landed.stderr
    assert world.meta("s-land")["gc.outcome"] == "pass"
    assert git(world.rig, "rev-parse", f"refs/heads/lite/{ANCHOR}") == commit


def test_land_refuses_without_an_approved_attempt(world: World) -> None:
    prepared(world)
    result = world.claim_and_run("s-land", "land", "land")
    assert result.returncode == 0
    assert world.meta("s-land")["gc.outcome"] == "fail"
    assert "no approved attempt" in world.bead("s-land")["close_reason"]


def test_land_refuses_when_a_sibling_moved_the_target(world: World) -> None:
    sealed(world)
    attempted(world, "t1", "fixed\n")
    assert verified(world, "t1").returncode == 0
    assert world.run("verdict", "approve").returncode == 0
    git(world.rig, "branch", f"lite/{ANCHOR}", "main")
    git(world.rig, "checkout", "-q", f"lite/{ANCHOR}")
    git(world.rig, "commit", "-q", "--allow-empty", "-m", "sibling")
    git(world.rig, "checkout", "-q", "main")
    result = world.claim_and_run("s-land", "land", "land")
    assert result.returncode == 0
    assert world.meta("s-land")["gc.outcome"] == "fail"
    assert "a sibling landed first" in world.bead("s-land")["close_reason"]
    assert world.meta(ANCHOR)["lite.result"] == "land-refused"
    assert world.bead(ANCHOR)["status"] == "open"


def test_close_anchor_fails_when_close_is_refused(world: World) -> None:
    state = world.state
    state["beads"][ANCHOR]["metadata"].update({"lite.landed_commit": git(world.rig, "rev-parse", "main"), "target": "main"})
    state["refuse_close"] = [ANCHOR]
    world.save(state)
    result = world.claim_and_run("s-close", "close-anchor", "close-anchor")
    assert result.returncode == 0
    assert world.meta("s-close")["gc.outcome"] == "fail"
    assert world.bead(ANCHOR)["status"] == "open"


# --- several cards ------------------------------------------------------------------

CARD_2 = (
    CARD.replace('kind = "bugfix"', 'kind = "tdd-feature"')
    .replace("grep -q fixed src/app.txt", "grep -q polished src/app.txt")
    .replace("The app prints fixed.", "The app prints fixed and polished.")
    .replace("1. Replace broken with fixed.", "1. Add polished after fixed.")
)


def sealed_two(world: World) -> None:
    prepared(world)
    world.draft(1).write_text(CARD)
    world.draft(2).write_text(CARD_2)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 0, result.stderr


def pass_first_card(world: World) -> str:
    """Pass card 1 at t1 and return its commit."""
    attempted(world, "t1", "fixed\n", name="s-att-c1")
    assert verified(world, "t1", name="s-ver-c1").returncode == 0
    approved = world.run("verdict", "approve")
    assert approved.returncode == 0, approved.stderr
    return world.meta("s-att-c1")["lite.attempt_commit"]


def test_cut_card_finish_seals_several_drafts_in_order(world: World) -> None:
    sealed_two(world)
    meta = world.meta(ANCHOR)
    assert meta["lite.cards"] == "2" and meta["lite.card"] == "1"
    assert meta["lite.kind"] == "bugfix,tdd-feature"
    assert meta["lite.card.1.kind"] == "bugfix" and meta["lite.card.2.kind"] == "tdd-feature"
    assert "grep -q fixed src/app.txt" in (world.card_dir(1) / "card.md").read_text()
    second = (world.card_dir(2) / "card.md").read_text()
    assert "grep -q polished src/app.txt" in second
    assert second.rstrip().endswith((PACK / "assets" / "kinds" / "tdd-feature.md").read_text().strip())
    assert "sealed 2 cards" in world.bead("s-cut")["close_reason"]


def test_one_card_of_one_kind_records_the_plain_kind(world: World) -> None:
    sealed(world)
    meta = world.meta(ANCHOR)
    assert meta["lite.cards"] == "1" and meta["lite.kind"] == "bugfix"
    assert not any(key.startswith("lite.card.") for key in meta)


def test_cut_card_finish_reports_the_errors_of_every_card_by_number(world: World) -> None:
    prepared(world)
    world.draft(1).write_text(CARD.replace("## Goal", "## Goals"))
    world.draft(2).write_text(CARD_2.replace('id = "st-1"', 'id = "st-9"'))
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1
    assert "card 1: missing section '## Goal'" in result.stderr
    assert "card 2: the card id must be st-1, not st-9" in result.stderr
    assert world.bead("s-cut")["status"] == "in_progress"
    assert "lite.cards" not in world.meta(ANCHOR)


def test_cut_card_finish_checks_context_quotes_in_every_card(world: World) -> None:
    prepared(world)
    world.draft(1).write_text(CARD)
    world.draft(2).write_text(CARD_2.replace("## Context\n", "## Context\n\n```\nmade up line\n```\n"))
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "card 2: '## Context' code must quote the repository" in result.stderr


def test_cut_card_finish_refuses_a_gap_in_the_numbering(world: World) -> None:
    prepared(world)
    world.draft(1).write_text(CARD)
    world.draft(3).write_text(CARD_2)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "missing 2.md" in result.stderr
    assert world.bead("s-cut")["status"] == "in_progress"


def test_cut_card_finish_refuses_a_stray_file_among_the_drafts(world: World) -> None:
    prepared(world)
    world.draft(1).write_text(CARD)
    (world.artifacts / "drafts" / "notes.md").write_text("thinking")
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "notes.md is not a card draft" in result.stderr


def test_cut_card_finish_needs_a_draft(world: World) -> None:
    prepared(world)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "no card drafts in" in result.stderr


def test_cut_card_finish_refuses_more_cards_than_the_cap(world: World) -> None:
    prepared(world)
    for number in range(1, 12):
        world.draft(number).write_text(CARD)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-finish")
    assert result.returncode == 1 and "11 cards; the cap is 10" in result.stderr


def test_cut_card_start_offers_several_cards(world: World) -> None:
    prepared(world)
    result = world.claim_and_run("s-cut", "cut-card", "cut-card-start")
    assert result.returncode == 0, result.stderr
    assert "1.md, 2.md, ... (at most 10)" in result.stdout


def test_approving_a_card_with_cards_left_moves_to_the_next_card_at_t1(world: World) -> None:
    sealed_two(world)
    commit = pass_first_card(world)
    assert output(world, "s-ver-c1") == {"next": [{"action": "t1", "round": "1"}]}
    assert world.meta("s-ver-c1")["gc.outcome"] == "pass"
    assert "card 1 of 2 t1 approve" in world.bead("s-ver-c1")["close_reason"]
    meta = world.meta(ANCHOR)
    assert meta["lite.card"] == "2"
    assert meta["lite.card.2.base_commit"] == commit
    assert meta["lite.card.1.attempt.t1"] == "approved" and meta["lite.card.1.passed_tier"] == "t1"
    assert "lite.passed_tier" not in meta and "lite.attempt.t1" not in meta
    assert "lite.card.1.card_overlap.t1" in meta and "lite.card.1.files_touched.t1" in meta
    assert world.meta("s-att-c1")["lite.card"] == "1" and world.meta("s-ver-c1")["lite.card"] == "1"
    assert git(world.worktree, "log", "-1", "--format=%s") == "st-1 (1/2 t1): t1 change"
    assert (world.card_dir(1) / "attempts" / "t1" / "report.md").exists()


def test_land_refuses_an_item_whose_last_card_has_not_passed(world: World) -> None:
    sealed_two(world)
    pass_first_card(world)
    result = world.claim_and_run("s-land", "land", "land")
    assert result.returncode == 0
    assert world.meta("s-land")["gc.outcome"] == "fail"
    assert "no approved attempt" in world.bead("s-land")["close_reason"]


def test_the_next_card_starts_from_the_previous_card_and_says_so(world: World) -> None:
    sealed_two(world)
    commit = pass_first_card(world)
    started = world.claim_and_run("s-att-c2", "attempt", "attempt-start", tier="t1")
    assert started.returncode == 0, started.stderr
    assert git(world.worktree, "rev-parse", "HEAD") == commit
    assert "Attempt T1 for st-1, card 2 of 2." in started.stdout
    assert str(world.card_dir(2) / "card.md") in started.stdout
    assert "Cards 1 to 1 are" in started.stdout
    assert "rejected" not in started.stdout


def test_the_last_card_lands_every_card_and_records_the_highest_tier(world: World) -> None:
    sealed_two(world)
    first = pass_first_card(world)
    attempted(world, "t1", "fixed\n", name="s-att-c2")
    assert verified(world, "t1", name="s-ver-c2").returncode == 0
    assert output(world, "s-ver-c2") == {"next": [{"action": "t1", "round": "2"}]}
    assert world.meta(ANCHOR)["lite.card.2.last_rejected"] == "t1"
    findings = world.card_dir(2) / "attempts" / "t1" / "findings.md"
    assert "## card-done" in findings.read_text()
    attempted(world, "t1", "fixed\n", round_="2", name="s-att-c2r")
    assert verified(world, "t1", "2", name="s-ver-c2r").returncode == 0
    assert output(world, "s-ver-c2r") == {"next": [{"action": "t2", "round": "1"}]}
    started = world.claim_and_run("s-att-c2t2", "attempt", "attempt-start", tier="t2")
    assert started.returncode == 0, started.stderr
    assert git(world.worktree, "rev-parse", "HEAD") == first
    assert "reset to where card 2 of 2 starts" in started.stdout
    (world.worktree / "src" / "app.txt").write_text("fixed\npolished\n")
    assert world.run("attempt-finish", "--summary", "t2 polish").returncode == 0
    result = verified(world, "t2", name="s-ver-c2t2")
    assert result.returncode == 0, result.stderr
    assert "This is card 2 of 2" in result.stdout
    diff = (world.card_dir(2) / "attempts" / "t2" / "attempt.diff").read_text()
    assert "+polished" in diff and "+fixed" not in diff
    assert world.run("verdict", "approve").returncode == 0
    assert output(world, "s-ver-c2t2") == {"next": [{"action": "land", "round": "1"}]}
    meta = world.meta(ANCHOR)
    assert meta["lite.card.2.passed_tier"] == "t2" and meta["lite.passed_tier"] == "t2"
    landed = world.claim_and_run("s-land", "land", "land")
    assert landed.returncode == 0, landed.stderr
    branch = f"refs/heads/lite/{ANCHOR}"
    assert git(world.rig, "rev-parse", branch) == git(world.worktree, "rev-parse", "HEAD")
    subjects = git(world.rig, "log", "--format=%s", f"main..{branch}").splitlines()
    assert subjects == ["st-1 (2/2 t2): t2 polish", "st-1 (1/2 t1): t1 change"]


def test_the_last_card_refuses_to_land_when_an_earlier_card_never_passed(world: World) -> None:
    sealed_two(world)
    pass_first_card(world)
    state = world.state
    del state["beads"][ANCHOR]["metadata"]["lite.card.1.passed_tier"]
    world.save(state)
    attempted(world, "t1", "fixed\npolished\n", name="s-att-c2")
    assert verified(world, "t1", name="s-ver-c2").returncode == 0
    result = world.run("verdict", "approve")
    assert result.returncode == 1 and "card 1 never passed" in result.stderr
    assert world.bead("s-ver-c2")["status"] != "closed"
    assert "lite.passed_tier" not in world.meta(ANCHOR)


def test_a_verify_step_retried_after_the_anchor_moved_on_keeps_its_card(world: World) -> None:
    sealed_two(world)
    attempted(world, "t1", "fixed\n", name="s-att-c1")
    assert verified(world, "t1", name="s-ver-c1").returncode == 0
    state = world.state
    state["beads"][ANCHOR]["metadata"].update({"lite.card": "2", "lite.card.2.base_commit": "0" * 40})
    world.save(state)
    approved = world.run("verdict", "approve")
    assert approved.returncode == 0, approved.stderr
    meta = world.meta(ANCHOR)
    assert meta["lite.card.1.attempt.t1"] == "approved"
    assert meta["lite.card.2.base_commit"] == world.meta("s-att-c1")["lite.attempt_commit"]


def test_t3_mail_names_the_card(world: World) -> None:
    sealed_two(world)
    attempted(world, "t2", "fixed\n", name="s-att-c1")
    assert verified(world, "t2", name="s-ver-c1").returncode == 0
    assert world.run("verdict", "reject", "--reason", "src/app.txt:1 wrong").returncode == 0
    assert "failed at t1 and t2 on card 1 of 2" in world.state["mail"][0]["body"]


def test_an_item_cut_before_cards_were_numbered_keeps_its_root_card(world: World) -> None:
    prepared(world)
    sealed_text = cards.seal(CARD, (PACK / "assets" / "kinds" / "bugfix.md").read_text())
    assert isinstance(sealed_text, Ok)
    (world.artifacts / "card.md").write_text(sealed_text.value)
    attempted(world, "t1", "fixed\n")
    assert verified(world, "t1").returncode == 0
    assert world.run("verdict", "approve").returncode == 0
    assert output(world, "s-ver-t1") == {"next": [{"action": "land", "round": "1"}]}
    meta = world.meta(ANCHOR)
    assert meta["lite.passed_tier"] == "t1" and meta["lite.attempt.t1"] == "approved"
    assert (world.artifacts / "attempts" / "t1" / "report.md").exists()
    assert not (world.artifacts / "cards").exists()
    assert "lite.card" not in world.meta("s-ver-t1")


def test_cut_card_start_clears_drafts_of_an_earlier_run_but_not_its_own(world: World) -> None:
    prepared(world)
    world.draft(2).write_text("left by an earlier run")
    started = world.claim_and_run("s-cut", "cut-card", "cut-card-start")
    assert started.returncode == 0, started.stderr
    assert not (world.artifacts / "drafts").exists()
    assert world.meta("s-cut")["lite.cut_started"] == "true"
    world.draft(1).write_text(CARD)
    again = world.run("cut-card-start")
    assert again.returncode == 0, again.stderr
    assert world.draft(1).read_text() == CARD
    finished = world.run("cut-card-finish")
    assert finished.returncode == 0, finished.stderr
    assert world.meta(ANCHOR)["lite.cards"] == "1"
