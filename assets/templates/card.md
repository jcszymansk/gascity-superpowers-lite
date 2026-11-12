+++
schema = "lite.card.v1"
id = "{id}"
kind = "bugfix"                     # bugfix or tdd-feature
files = ["path/one", "path/two/**/*.kt"]    # every file the change may create or touch: paths or patterns, no limit
done_when = ["exact command"]       # commands that must exit 0 in the worktree, at most 8
+++

## Goal

One or two sentences: what is true when the task is done.

## Interfaces

Every signature or type to add or change, in a code block, without bodies. "None." if nothing
changes.

## Context

Excerpts of the code the change depends on, each with its path and line range, so the
executor never has to search. Code blocks here must quote the repository exactly: no new code,
line numbers or elisions; use one block per excerpt.

## Steps

Numbered steps that say what to change and why, and each test by name with the behaviour it
pins down. No code: the executor writes the tests and the implementation.

## Out of scope

What not to touch, and when to stop and report a blocker instead of improvising.
