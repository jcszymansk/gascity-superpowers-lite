"""Consistency of the lite v2 pack files: formulas, step texts, agents, slots and commands."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

PACK = Path(__file__).resolve().parents[2]
V2_FORMULAS = ("superpowers-lite-work", "superpowers-lite-work-item", "superpowers-lite-next")
AGENTS = ("operator", "card-cutter", "executor-t1", "executor-t2", "executor-t3", "card-reviewer")
SLOTS = ("lite-t1", "lite-t2", "lite-t3", "lite-plan", "lite-review", "lite-review-cross", "lite-ops")
STEP_COMMANDS = {
    "prepare-worktree": {"prepare-worktree"},
    "cut-card": {"cut-card-start", "cut-card-finish"},
    "attempt": {"attempt-start", "attempt-finish"},
    "verify": {"verify", "verdict"},
    "approval": {"approval"},
    "land": {"land"},
    "close-anchor": {"close-anchor"},
}
COMMAND_RE = re.compile(r"gc superpowers-lite ([a-z-]+)")


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _steps(name: str) -> list[dict[str, Any]]:
    data = _toml(PACK / "formulas" / f"{name}.formula.toml")
    steps: list[dict[str, Any]] = data.get("steps", []) + data.get("template", [])
    return steps


def _commands() -> set[str]:
    return {path.name for path in (PACK / "commands").iterdir() if path.is_dir()}


@pytest.mark.parametrize("name", V2_FORMULAS)
def test_every_step_routes_to_a_lite_agent(name: str) -> None:
    for step in _steps(name):
        target = step["metadata"]["gc.run_target"]
        agent = target.removeprefix("superpowers-lite.").replace("{action}", "t1")
        assert target.startswith("superpowers-lite."), step["id"]
        assert agent in AGENTS, step["id"]


@pytest.mark.parametrize("name", V2_FORMULAS[1:])
def test_every_step_text_exists_and_names_its_commands(name: str) -> None:
    formula_dir = PACK / "formulas"
    for step in _steps(name):
        kind = step["metadata"]["lite.step"]
        text = (formula_dir / step["description_file"]).resolve().read_text(encoding="utf-8")
        assert set(COMMAND_RE.findall(text)) == STEP_COMMANDS[kind], step["id"]
        assert len(text.encode()) < 4096, step["id"]


def test_step_kinds_match_the_commands_that_check_them() -> None:
    source = (PACK / "assets" / "litetools" / "commands.py").read_text(encoding="utf-8")
    expected = set(re.findall(r'_claimed_step\(ctx, "([a-z-]+)"\)', source))
    used = {step["metadata"]["lite.step"] for name in V2_FORMULAS[1:] for step in _steps(name)}
    assert used == expected == set(STEP_COMMANDS)


def test_tiered_steps_carry_their_tier() -> None:
    for name in V2_FORMULAS[1:]:
        for step in _steps(name):
            if step["metadata"]["lite.step"] in {"attempt", "verify"}:
                assert step["metadata"]["lite.tier"] in {"t1", "{action}"}, step["id"]


def test_every_command_has_a_runner_and_a_cli_subcommand() -> None:
    cli = (PACK / "assets" / "litetools" / "cli.py").read_text(encoding="utf-8")
    for command in _commands():
        run = (PACK / "commands" / command / "run.sh").read_text(encoding="utf-8")
        assert f"assets/lite.py\" {command} " in run, command
        assert f'"{command}"' in cli, command
    named = {c for path in (PACK / "assets" / "workflows" / "superpowers-lite-work-item").glob("*.md")
             for c in COMMAND_RE.findall(path.read_text(encoding="utf-8"))}
    prompts = {c for path in (PACK / "agents").glob("*/prompt.template.md")
               for c in COMMAND_RE.findall(path.read_text(encoding="utf-8"))}
    fragment = COMMAND_RE.findall((PACK / "template-fragments" / "lite-step-worker.template.md").read_text(encoding="utf-8"))
    assert named | prompts | set(fragment) <= _commands()


def test_agents_use_only_slots() -> None:
    assert sorted(path.name for path in (PACK / "agents").iterdir()) == sorted(AGENTS)
    for agent in AGENTS:
        config = _toml(PACK / "agents" / agent / "agent.toml")
        assert config["scope"] == "rig"
        assert config["provider"] in SLOTS
        assert "option_defaults" not in config
        prompt = (PACK / "agents" / agent / "prompt.template.md").read_text(encoding="utf-8")
        assert '{{ template "lite-step-worker" . }}' in prompt


def test_slots_set_model_and_effort_or_inherit() -> None:
    providers = _toml(PACK / "pack.toml")["providers"]
    assert sorted(providers) == sorted(SLOTS)
    for name, slot in providers.items():
        if slot["base"].startswith("provider:"):
            assert slot["base"].removeprefix("provider:") in SLOTS, name
        else:
            assert set(slot["option_defaults"]) >= {"model", "effort"}, name
            assert slot["option_defaults"]["model"].startswith("claude-"), name
