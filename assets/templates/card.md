+++
schema = "lite.card.v1"
id = "{id}"
kind = "bugfix"                     # bugfix or tdd-feature
files = ["path/one", "path/two"]    # every file the executor may create or change, at most 8
done_when = ["exact command"]       # commands that must exit 0 in the worktree, at most 8
+++

## Goal

One or two sentences: what is true when the task is done.

## Interfaces

Every signature or type to add or change, written out in full. "None." if nothing changes.

## Context

Excerpts of the code the change depends on, each with its path and line range, so the
executor never has to search.

## Steps

Numbered steps, with the code each step adds and the tests it writes.

## Out of scope

What not to touch, and when to stop and report a blocker instead of improvising.
