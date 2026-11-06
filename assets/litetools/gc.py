"""A narrow wrapper around the ``gc`` CLI.

Every call returns a ``Result``; nothing here raises for an expected gc
failure. Only the subcommands lite needs are exposed, so a command can never
reach for a broad query or a bead it did not resolve.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Mapping

from litetools.result import Err, Ok, Result

log = logging.getLogger(__name__)

GC_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class Bead:
    """The fields of a bead that lite reads.

    Attributes:
        bead_id: The bead id.
        status: ``open``, ``in_progress`` or ``closed``.
        title: The bead title.
        description: The bead description.
        assignee: The current assignee, or an empty string.
        metadata: The bead's metadata, values as strings.
    """

    bead_id: str
    status: str
    title: str
    description: str
    assignee: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def meta(self, key: str) -> str:
        """Return metadata ``key`` stripped, or an empty string."""
        return self.metadata.get(key, "").strip()


def bead_from_json(data: object) -> Result[Bead, str]:
    """Build a ``Bead`` from ``gc bd show --json`` output (object or 1-list)."""
    if isinstance(data, list):
        if len(data) != 1:
            return Err(f"expected one bead, got {len(data)}")
        data = data[0]
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return Err("bead JSON has no string 'id'")
    raw_meta = data.get("metadata") or {}
    if not isinstance(raw_meta, dict):
        return Err(f"bead {data['id']} has non-object metadata")
    metadata = {str(k): v if isinstance(v, str) else json.dumps(v) for k, v in raw_meta.items()}
    return Ok(
        Bead(
            bead_id=data["id"],
            status=str(data.get("status") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            assignee=str(data.get("assignee") or ""),
            metadata=metadata,
        )
    )


@dataclass(frozen=True, slots=True)
class Gc:
    """Runs ``gc`` subcommands.

    Attributes:
        binary: The gc executable to run.
        env: The environment for gc, normally the agent's own.
        rig: The rig whose bead store every ``bd`` call uses. Empty lets gc
            pick the store from the working directory, which a worktree
            outside the rig would get wrong, so agents always set it.
    """

    binary: str
    env: Mapping[str, str]
    rig: str = ""

    def run(self, *args: str) -> Result[str, str]:
        """Run ``gc args...`` and return stdout, or an error naming the call."""
        log.debug("gc %s", " ".join(args))
        try:
            proc = subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                env=dict(self.env),
                timeout=GC_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return Err(f"gc {args[0] if args else ''} could not run: {error}")
        if proc.returncode != 0:
            first = (proc.stderr.strip() or proc.stdout.strip()).splitlines()[:1]
            return Err(f"gc {' '.join(args[:2])} exited {proc.returncode}: {first[0] if first else ''}")
        return Ok(proc.stdout)

    def bd(self, *args: str) -> Result[str, str]:
        """Run ``gc bd args...`` against this rig's bead store."""
        scope = ("--rig", self.rig) if self.rig else ()
        return self.run("bd", *scope, *args)

    def show(self, bead_id: str) -> Result[Bead, str]:
        """Read one bead."""
        if not bead_id.strip():
            return Err("refusing to read a bead with an empty id")
        out = self.bd("show", bead_id, "--json")
        if isinstance(out, Err):
            return out
        try:
            data = json.loads(out.value)
        except json.JSONDecodeError as error:
            return Err(f"gc bd show {bead_id} printed invalid JSON: {error}")
        return bead_from_json(data)

    def set_metadata(self, bead_id: str, values: Mapping[str, str]) -> Result[None, str]:
        """Set metadata keys on one bead."""
        if not bead_id.strip():
            return Err("refusing to update a bead with an empty id")
        if not values:
            return Ok(None)
        args = ["update", bead_id]
        for key, value in values.items():
            args += ["--set-metadata", f"{key}={value}"]
        out = self.bd(*args)
        return out if isinstance(out, Err) else Ok(None)

    def close(self, bead_id: str, reason: str) -> Result[None, str]:
        """Close one bead with a reason."""
        if not bead_id.strip():
            return Err("refusing to close a bead with an empty id")
        out = self.bd("close", bead_id, "--reason", reason)
        return out if isinstance(out, Err) else Ok(None)

    def claim(self) -> Result[dict[str, object], str]:
        """Run ``gc hook --claim --drain-ack --json`` and return its JSON."""
        out = self.run("hook", "--claim", "--drain-ack", "--json")
        if isinstance(out, Err):
            return out
        try:
            data = json.loads(out.value)
        except json.JSONDecodeError as error:
            return Err(f"gc hook --claim printed invalid JSON: {error}")
        if not isinstance(data, dict):
            return Err("gc hook --claim did not print a JSON object")
        return Ok(data)
