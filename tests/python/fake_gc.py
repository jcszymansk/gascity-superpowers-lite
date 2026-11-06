#!/usr/bin/env python3
"""A stand-in for the ``gc`` CLI, backed by the JSON file in ``FAKE_GC_STATE``.

It implements only the calls the pack commands make, and records every call
in ``state["calls"]`` so tests can assert on side effects.
"""

import json
import os
import sys


def main(argv: list[str]) -> int:
    path = os.environ["FAKE_GC_STATE"]
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    state.setdefault("calls", []).append(argv)
    code = handle_call(state, argv)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)
    return code


def flag_values(args: list[str], name: str) -> list[str]:
    values = []
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            values.append(args[index + 1])
        elif arg.startswith(name + "="):
            values.append(arg.split("=", 1)[1])
    return values


def handle_call(state: dict, argv: list[str]) -> int:
    beads = state["beads"]
    if argv[:1] == ["--city"] and argv[2:4] == ["rig", "list"]:
        print(json.dumps({"rigs": state.get("rigs", [])}))
        return 0
    if argv[:2] == ["bd", "show"]:
        bead = beads.get(argv[2])
        if bead is None:
            print(f"no issue found: {argv[2]}", file=sys.stderr)
            return 1
        print(json.dumps([bead]))
        return 0
    if argv[:2] == ["bd", "update"]:
        bead = beads.get(argv[2])
        if bead is None:
            return 1
        expect = flag_values(argv, "--if-assignee")
        if expect and bead.get("assignee", "") != expect[0]:
            print("assignee mismatch", file=sys.stderr)
            return 1
        for pair in flag_values(argv, "--set-metadata"):
            key, value = pair.split("=", 1)
            bead.setdefault("metadata", {})[key] = value
        for key in flag_values(argv, "--unset-metadata"):
            bead.setdefault("metadata", {}).pop(key, None)
        if "--assignee=" in argv:
            bead["assignee"] = ""
        return 0
    if argv[:2] == ["bd", "close"]:
        bead = beads.get(argv[2])
        if bead is None or bead["id"] in state.get("refuse_close", []):
            print("cannot close: open dependency", file=sys.stderr)
            return 1
        bead["status"] = "closed"
        bead["close_reason"] = flag_values(argv, "--reason")[0]
        return 0
    if argv[:2] == ["bd", "list"]:
        wanted = [pair.split("=", 1) for pair in flag_values(argv, "--metadata-field")]
        kind = flag_values(argv, "--type")
        statuses = flag_values(argv, "--status")
        found = []
        for bead in beads.values():
            meta = bead.get("metadata", {})
            if any(meta.get(k) != v for k, v in wanted):
                continue
            if kind and bead.get("issue_type") != kind[0]:
                continue
            if statuses and bead.get("status") not in statuses[0].split(","):
                continue
            found.append(bead)
        print(json.dumps(found))
        return 0
    if argv[:2] == ["hook", "--claim"]:
        queue = state.get("claim_queue", [])
        if not queue:
            print(json.dumps({"action": "drain"}))
            return 0
        bead_id = queue.pop(0)
        beads[bead_id]["assignee"] = state.get("me", "")
        beads[bead_id]["status"] = "in_progress"
        # gc 1.5.1 records the claiming session on the bead as well.
        beads[bead_id].setdefault("metadata", {}).update(
            {"gc.claimed_at": "2026-01-01T00:00:00Z", "gc.session_id": "s-1", "gc.session_name": "worker-s-1"}
        )
        print(json.dumps({"action": "work", "bead_id": bead_id, "assignee": state.get("me", "")}))
        return 0
    if argv[:2] == ["runtime", "drain-ack"]:
        state["drained"] = state.get("drained", 0) + 1
        return 0
    if argv[:2] == ["mail", "send"]:
        state.setdefault("mail", []).append({"to": argv[2], "subject": flag_values(argv, "-s")[0], "body": flag_values(argv, "-m")[0]})
        return 0
    print(f"fake gc: unsupported call {argv}", file=sys.stderr)
    return 9


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
