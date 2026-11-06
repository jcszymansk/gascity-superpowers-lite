"""Command-line entry: ``gc superpowers-lite <command> [args]``.

Exit status 0 means the command did its job (which may be closing a step as
failed); 1 means it refused or could not run, and the step is unchanged
unless the message says otherwise; 2 is a usage error.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from litetools import commands
from litetools.commands import Ctx, Outcome
from litetools.context import load_env
from litetools.gc import Gc
from litetools.ladder import Verdict
from litetools.result import Err

log = logging.getLogger("litetools")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gc superpowers-lite")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("claim", "prepare-worktree", "cut-card-start", "attempt-start", "verify", "approval", "land", "close-anchor"):
        sub.add_parser(name)
    finish_card = sub.add_parser("cut-card-finish")
    finish_card.add_argument("--blocked", help="the work bead cannot become a card, and why")
    finish = sub.add_parser("attempt-finish")
    finish.add_argument("--summary", help="what the attempt changed and why")
    finish.add_argument("--blocked", help="why the card cannot be done as written")
    decide = sub.add_parser("verdict")
    decide.add_argument("choice", choices=[v.value for v in Verdict])
    decide.add_argument("--reason", help="the problems found; required to reject")
    approve = sub.add_parser("approve")
    approve.add_argument("--rig", help="the rig that holds the work bead (default: $GC_RIG, else the current directory's)")
    approve.add_argument("anchor", help="the work bead whose t3 attempt to approve")
    return parser


def _setup_logging(environ: Mapping[str, str]) -> None:
    level = getattr(logging, environ.get("LITE_LOG_LEVEL", "INFO").upper(), logging.INFO)
    log.setLevel(logging.DEBUG)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(level)
    stderr.setFormatter(logging.Formatter("lite: %(levelname)s %(message)s"))
    log.addHandler(stderr)
    city = environ.get("GC_CITY", "").strip()
    if city:
        path = Path(city) / ".gc" / "runtime" / "superpowers-lite" / "commands.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
        except OSError:
            return
        handler.setLevel(logging.DEBUG)
        who = environ.get("GC_SESSION_NAME") or environ.get("GC_AGENT") or "?"
        handler.setFormatter(logging.Formatter(f"%(asctime)s {who} %(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)


def _dispatch(ctx: Ctx, args: argparse.Namespace) -> Outcome:
    simple: dict[str, Callable[[Ctx], Outcome]] = {
        "claim": commands.claim,
        "prepare-worktree": commands.prepare_worktree,
        "cut-card-start": commands.cut_card_start,
        "attempt-start": commands.attempt_start,
        "verify": commands.verify,
        "approval": commands.approval,
        "land": commands.land,
        "close-anchor": commands.close_anchor,
    }
    if args.command in simple:
        return simple[args.command](ctx)
    if args.command == "cut-card-finish":
        return commands.cut_card_finish(ctx, args.blocked)
    if args.command == "attempt-finish":
        return commands.attempt_finish(ctx, args.summary, args.blocked)
    if args.command == "verdict":
        return commands.verdict(ctx, Verdict(args.choice), args.reason)
    return Err(f"no handler for {args.command}")


def main(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    """Run one command and return its exit status."""
    args = _parser().parse_args(list(argv))
    _setup_logging(environ)
    log.debug("%s %s", args.command, " ".join(argv[1:]))
    binary = environ.get("LITE_GC_BIN", "gc")
    if args.command == "approve":
        rig = args.rig or environ.get("GC_RIG", "").strip()
        return _report(args.command, commands.approve(Gc(binary, dict(environ), rig), args.anchor), None)
    env = load_env(environ)
    if isinstance(env, Err):
        print(f"gc superpowers-lite {args.command}: {env.error}", file=sys.stderr)
        return 1
    gc = Gc(binary, dict(environ), env.value.rig)
    return _report(args.command, _dispatch(Ctx(env.value, gc), args), gc)


def _report(command: str, result: Outcome, gc: Gc | None) -> int:
    """Print a command's outcome, drain-ack when it asks to, and return the exit status."""
    if isinstance(result, Err):
        log.error("%s refused: %s", command, result.error)
        print(f"gc superpowers-lite {command}: {result.error}", file=sys.stderr)
        return 1
    print(result.value.message, flush=True)
    if result.value.drain and gc is not None:
        acked = gc.run("runtime", "drain-ack")
        if isinstance(acked, Err):
            log.warning("drain-ack failed: %s", acked.error)
            print("Now run `gc runtime drain-ack` and exit.")
    return 0


def run() -> None:
    """Process entry point."""
    sys.exit(main(sys.argv[1:], os.environ))
