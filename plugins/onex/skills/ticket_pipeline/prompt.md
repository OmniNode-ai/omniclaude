# ticket_pipeline prompt

You are executing the **ticket-pipeline** skill. This skill is a thin dispatch-only
shim that routes to the `node_ticket_pipeline` node in omnimarket. All FSM logic,
phase execution, CI watching, PR review, and merge orchestration lives in the node
handler — the shim does not implement any pipeline logic itself.

## Announce

Say: "I'm using the ticket-pipeline skill to run the autonomous per-ticket pipeline."

## Parse arguments

Extract from `$ARGUMENTS`:

- `ticket_id` (required) — Linear ticket ID (e.g., `OMN-1234`)
- `--skip-to <phase>` — Resume from phase (pre_flight|implement|local_review|create_pr|test_iterate|ci_watch|pr_review_loop|review_gate|integration_verification_gate|auto_merge|worktree_cleanup)
- `--dry-run` — No commits, pushes, or PRs
- `--skip-test-iterate` — Skip the test-fix loop
- `--auto-merge` — Force auto_merge policy on
- `--docs-only` — Assert all changes are documentation-only; skips integration verification

Validate `ticket_id` matches pattern `[A-Z]+-\d+`. Exit with an error if missing or malformed.

## Execution: Dispatch to node_ticket_pipeline

Build the JSON input from parsed flags and dispatch via `onex run-node`. No inline
FSM logic, no shell wrappers, no script fallbacks.

```bash
onex run-node node_ticket_pipeline \
  --input '{"ticket_id": "<ticket_id>", "skip_to": <skip_to_or_null>, "skip_test_iterate": <bool>, "dry_run": <bool>}' \
  --timeout 600
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it
directly, do not produce prose.

## Post-dispatch: Render results

Parse the node output (`ModelPipelineState` JSON) and display:

```
Ticket Pipeline — <ticket_id>
==============================
Final phase  : <final_phase>
PR URL       : <pr_url or "none">
Phase results: <phase_results summary>
```

If the pipeline reached FAILED state, display the failure reason and last successful
phase. Do not attempt inline recovery — the node owns all retry and circuit-breaker logic.

## Error handling

- If `onex run-node node_ticket_pipeline` fails: surface the `SkillRoutingError`
  JSON envelope from stdout/stderr and exit non-zero.
- Do not fall back to inline phase execution, task dispatch, or shell scripts.
  The node is the single source of truth for pipeline logic (A4 amendment).
