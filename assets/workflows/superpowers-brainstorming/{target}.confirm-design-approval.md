Confirm Superpowers design approval.

This lane represents the stock `User approves design?` gate before writing the
spec. Use workflow root metadata `gc.var.brainstorming_approval_mode` when
present; otherwise default to `autonomous`.

In `interactive` mode, use the passive wait + mail human gate pattern. This is
not a timeout-driven task.

1. Before waiting, update workflow root metadata with:
   - `gc.build.design_gate_status=waiting-human`
   - `gc.build.design_gate_bead_id=<this bead id>`
   - `gc.build.design_gate_artifact_path=<approval-summary path>`
   - preserve any existing `gc.build.design_gate_mail_sent=true`
2. Register a wait on this bead so the session stays put while the human
   decides:
   ```bash
   SESSION_TARGET="${GC_SESSION_ID:-${GC_SESSION_NAME:-}}"
   SESSION_NAME="${GC_SESSION_NAME:-$SESSION_TARGET}"
   WAIT_NOTE="Waiting for human approval of Superpowers design on bead $GC_BEAD_ID."
   if [ -n "$SESSION_NAME" ]; then
     WAIT_NOTE="$WAIT_NOTE Answer with: gc session nudge $SESSION_NAME '<answer>'"
   fi
   if [ -n "$SESSION_TARGET" ] && ! gc wait list --session "$SESSION_TARGET" | grep -Fq "$WAIT_NOTE"; then
     gc session wait "$SESSION_TARGET" \
       --on-beads "$GC_BEAD_ID" \
       --note "$WAIT_NOTE"
   fi
   ```
   Do not pass `--sleep`. In gc 1.5.1 a sleeping waiter that holds a claimed
   bead is drained, recorded as idle and stranded, which releases this bead and
   restarts the gate in a new session that the human's answer cannot reach.
   Without `--sleep` the session stays awake at its prompt, keeps its claim and
   costs nothing while idle. Never run `gc runtime drain-ack` while this bead
   is open, whatever the worker loop says about session boundaries. After the
   mail below, end your turn and do nothing else.
3. If workflow root metadata does not already have
   `gc.build.design_gate_mail_sent=true`, send exactly one mail with
   `gc mail send human ...`. Include the design candidate path, approval
   summary path, workflow root id, this bead id, the requested response
   options (approve, request changes, or reject), and how to answer:
   `gc session nudge <this session name> '<answer>'`. After sending, update workflow
   root metadata with `gc.build.design_gate_mail_sent=true` and
   `gc.build.design_gate_mail_to=human`.
4. Wait for explicit human feedback. It arrives as a nudge to this session,
   or is written under `Human response` in the approval summary or as
   a comment on this bead (read both when woken or resumed). If
   the session idles, detaches, or
   restarts before the human responds, do not close this bead. A resumed worker
   must read the gate metadata and continue waiting from this gate.
5. Use `done` only after explicit approval by setting
   `design_review.verdict=done`. If the human requests changes, record the
   requested revisions in the approval summary and close with
   `design_review.verdict=iterate`; that re-opens the design loop for another
   brainstorming pass. Close fail only for explicit rejection or abort, not for
   silence.

In `autonomous` mode, approve only when the design candidate has no unresolved
questions, no placeholders, and enough context to proceed without inventing
requirements. Otherwise close with `design_review.verdict=iterate`; that
re-opens the design loop for another brainstorming pass.

When iterating, write a concise revision summary that the next
`brainstorm-design` attempt can apply directly. The summary must name the
specific design sections, assumptions, or unresolved questions that caused the
loopback.

On approval, mark the design candidate approved and update workflow root
metadata with `gc.build.design_status=approved`,
`gc.build.design_path=<absolute path>`, `gc.build.design_gate_status=approved`,
and a short design summary. For a human-requested iteration, update
`gc.build.design_gate_status=revision_requested`.

Before closing, update the exact claimed bead id with the lane metadata. The
approval verdict metadata is `design_review.verdict=done|iterate`:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'design_review.verdict=done' \
  --set-metadata 'design_review.output_path=<approval-summary path>' \
  --set-metadata 'gc.continuation_group=superpowers-design-fixes'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Superpowers design approved.'
```

If the design needs another pass, set `design_review.verdict=iterate` instead
of `done` and name the required correction in the approval summary and close
reason. Do not pass `--metadata` or `--set-metadata` to `gc bd close`.

Do not invoke provider-native subagents or upstream plugin runtime commands.
This Gas City lane owns the design approval decision.
