"""The executor's attempt report, written by ``attempt-finish``, never by a model."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import Enum

from litetools.ladder import Tier
from litetools.result import Err, Ok, Result

SCHEMA = "lite.report.v1"


class Status(Enum):
    """How the executor ended its attempt."""

    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Report:
    """An attempt report.

    Attributes:
        card_id: The card the attempt worked on.
        tier: The attempt's tier.
        status: Whether the executor finished or stopped with a blocker.
        commit: The attempt's commit, or empty when it changed nothing.
        summary: The executor's own words.
    """

    card_id: str
    tier: Tier
    status: Status
    commit: str
    summary: str


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def render(report: Report) -> str:
    """Serialise a report."""
    return (
        "+++\n"
        f"schema = {_toml_string(SCHEMA)}\n"
        f"card = {_toml_string(report.card_id)}\n"
        f"tier = {_toml_string(report.tier.value)}\n"
        f"status = {_toml_string(report.status.value)}\n"
        f"commit = {_toml_string(report.commit)}\n"
        "+++\n\n## Summary\n\n"
        f"{report.summary.strip()}\n"
    )


def parse(text: str) -> Result[Report, str]:
    """Parse a report written by ``render``."""
    lines = text.splitlines()
    if len(lines) < 2 or lines[0] != "+++":
        return Err("the report does not start with '+++'")
    try:
        end = lines.index("+++", 1)
    except ValueError:
        return Err("the report front matter is not closed")
    try:
        meta = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as error:
        return Err(f"the report front matter is not valid TOML: {error}")
    if meta.get("schema") != SCHEMA:
        return Err(f"the report schema is not {SCHEMA}")
    tiers = {t.value: t for t in Tier}
    statuses = {s.value: s for s in Status}
    tier, status = tiers.get(str(meta.get("tier"))), statuses.get(str(meta.get("status")))
    card_id, commit = meta.get("card"), meta.get("commit")
    if tier is None or status is None or not isinstance(card_id, str) or not isinstance(commit, str):
        return Err("the report is missing card, tier, status or commit")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body.startswith("## Summary"):
        return Err("the report has no '## Summary' section")
    summary = body.removeprefix("## Summary").strip()
    if not summary:
        return Err("the report summary is empty")
    return Ok(Report(card_id, tier, status, commit, summary))
