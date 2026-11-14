"""How many attempts and rounds each tier gets, and where each number came from.

Each tier has two settings: ``attempts`` (fresh starts from the card's base)
and ``rounds`` (executor sessions within one attempt). A setting is read from,
highest precedence first::

    formula var   lite_t1_rounds        gc sling --var, or the rig's formula_vars
    city env      LITE_T1_ROUNDS        [workspace] env in city.toml
    pack default  PACK_DEFAULTS

gc stamps a sling ``--var`` and a rig's ``formula_vars`` on the item root the
same way (``gc.var.<name>``), so both count as the ``var`` source. The budget
is resolved once, when the item's worktree is prepared, and recorded on the
work bead (``lite.budget.t1.rounds``, ``lite.budget.t1.rounds.source``), so a
config edit during a run leaves running items as they started.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from litetools.ladder import Tier, TierLimits
from litetools.result import Err, Ok, Result

MAX_SETTING = 10
"""The largest attempts or rounds value accepted; it catches typos such as 30 for 3."""

_WHOLE_NUMBER = re.compile(r"[0-9]+")


class Kind(Enum):
    """The two settings each tier has."""

    ATTEMPTS = "attempts"
    ROUNDS = "rounds"


class Source(Enum):
    """Where a setting's value came from."""

    VAR = "var"
    ENV = "env"
    PACK = "pack"


@dataclass(frozen=True, slots=True)
class Setting:
    """One budget setting, such as T1 rounds.

    Attributes:
        tier: The tier it limits.
        kind: Attempts or rounds.
    """

    tier: Tier
    kind: Kind

    @property
    def var_name(self) -> str:
        """The formula var: ``lite_t1_rounds``."""
        return f"lite_{self.tier.value}_{self.kind.value}"

    @property
    def env_name(self) -> str:
        """The city environment variable: ``LITE_T1_ROUNDS``."""
        return self.var_name.upper()

    @property
    def key(self) -> str:
        """The work bead's record: ``lite.budget.t1.rounds``."""
        return f"lite.budget.{self.tier.value}.{self.kind.value}"


SETTINGS = tuple(Setting(tier, kind) for tier in Tier for kind in Kind)

PACK_DEFAULTS: Mapping[Setting, int] = {
    Setting(Tier.T1, Kind.ATTEMPTS): 1,
    Setting(Tier.T1, Kind.ROUNDS): 2,
    Setting(Tier.T2, Kind.ATTEMPTS): 1,
    Setting(Tier.T2, Kind.ROUNDS): 1,
    Setting(Tier.T3, Kind.ATTEMPTS): 1,
    Setting(Tier.T3, Kind.ROUNDS): 1,
}
"""Today's ladder: one T1 attempt with one retry, then one attempt each at T2 and T3."""


@dataclass(frozen=True, slots=True)
class Limit:
    """A setting's value and where it came from.

    Attributes:
        value: A whole number from 1 to ``MAX_SETTING``.
        source: The source that set it.
    """

    value: int
    source: Source


@dataclass(frozen=True, slots=True)
class Budget:
    """Every setting's limit.

    Attributes:
        limits: One limit per entry of ``SETTINGS``.
    """

    limits: Mapping[Setting, Limit]

    def limit(self, tier: Tier, kind: Kind) -> Limit:
        """Return the limit of ``tier``'s ``kind``."""
        return self.limits[Setting(tier, kind)]

    def tier_limits(self, tier: Tier) -> TierLimits:
        """Return the attempts and rounds of ``tier``, as the ladder takes them."""
        return TierLimits(self.limit(tier, Kind.ATTEMPTS).value, self.limit(tier, Kind.ROUNDS).value)

    def metadata(self) -> dict[str, str]:
        """Return the work bead records of every setting."""
        values: dict[str, str] = {}
        for setting in SETTINGS:
            limit = self.limits[setting]
            values[setting.key] = str(limit.value)
            values[f"{setting.key}.source"] = limit.source.value
        return values

    def summary(self) -> str:
        """Describe the budget in one line for logs: ``t1 1x2 (pack, var), ...``."""
        parts = []
        for tier in Tier:
            attempts, rounds = self.limit(tier, Kind.ATTEMPTS), self.limit(tier, Kind.ROUNDS)
            parts.append(f"{tier.value} {attempts.value}x{rounds.value} ({attempts.source.value}, {rounds.source.value})")
        return ", ".join(parts)


def _parse(raw: str, setting: Setting, origin: str) -> Result[int, str]:
    text = raw.strip()
    if not _WHOLE_NUMBER.fullmatch(text) or not 1 <= int(text) <= MAX_SETTING:
        return Err(f"{origin} is {raw!r}; {setting.kind.value} must be a whole number from 1 to {MAX_SETTING}")
    return Ok(int(text))


def resolve(formula_vars: Mapping[str, str], environ: Mapping[str, str]) -> Result[Budget, list[str]]:
    """Resolve every setting from the item's formula vars, the city env and the pack defaults.

    An empty or blank value counts as unset, so a formula can declare a var
    with an empty default. A value that is set but invalid is an error, never
    a reason to fall back to a lower source.

    Args:
        formula_vars: The item root's formula vars, by var name.
        environ: The session environment.

    Returns:
        The budget, or every invalid setting, each naming its source.
    """
    limits: dict[Setting, Limit] = {}
    errors: list[str] = []
    for setting in SETTINGS:
        candidates = (
            (formula_vars.get(setting.var_name, ""), Source.VAR, f"formula var {setting.var_name}"),
            (environ.get(setting.env_name, ""), Source.ENV, f"city env {setting.env_name}"),
        )
        chosen = next(((raw, source, origin) for raw, source, origin in candidates if raw.strip()), None)
        if chosen is None:
            limits[setting] = Limit(PACK_DEFAULTS[setting], Source.PACK)
            continue
        raw, source, origin = chosen
        parsed = _parse(raw, setting, origin)
        if isinstance(parsed, Err):
            errors.append(parsed.error)
        else:
            limits[setting] = Limit(parsed.value, source)
    return Err(errors) if errors else Ok(Budget(limits))


def recorded(metadata: Mapping[str, str]) -> Result[Budget, str]:
    """Read the budget an item recorded on its work bead.

    Args:
        metadata: The work bead's metadata.
    """
    limits: dict[Setting, Limit] = {}
    for setting in SETTINGS:
        raw_value = metadata.get(setting.key, "")
        if not raw_value.strip():
            return Err(f"the work bead has no {setting.key}; prepare-worktree records it")
        parsed = _parse(raw_value, setting, setting.key)
        if isinstance(parsed, Err):
            return parsed
        raw_source = metadata.get(f"{setting.key}.source", "").strip()
        source = next((s for s in Source if s.value == raw_source), None)
        if source is None:
            return Err(f"{setting.key}.source is {raw_source!r}, not one of {', '.join(s.value for s in Source)}")
        limits[setting] = Limit(parsed.value, source)
    return Ok(Budget(limits))
