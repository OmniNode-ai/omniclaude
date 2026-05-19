# ticket_work prompt

You are executing the **ticket-work** skill. This skill is a thin dispatch-only
shim that routes to the `node_ticket_work` node in omnimarket. All phase orchestration
(intake, research, questions, spec, implementation, review, done), contract management,
and Linear integration live in the node handler — the shim does not implement any
phase logic itself.

## Announce

Say: "I'm using the ticket-work skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `ticket_id` (required) — Linear ticket ID (e.g., `OMN-1807`)
- `--autonomous` — Skip human gates; proceed through all phases unattended
- `--skip-to <phase>` — Resume from named phase (intake|research|questions|spec|implementation|review|done)

Validate `ticket_id` matches pattern `[A-Z]+-\d+`. Exit with an error if missing or malformed.

## Execution: Dispatch to node_ticket_work

Build the JSON input from parsed flags and dispatch via `onex run-node`. No inline
phase logic, no LLM orchestration, no tracker calls.

### Tracker DI contract

The dispatched `node_ticket_work` handler owns Linear access through
`ProtocolProjectTracker` DI, resolved with `resolve_project_tracker()`. This
prompt must not call `tracker.*` directly; it preserves the tracker DI boundary
by routing all ticket work through the node.

```bash
onex run-node node_ticket_work \
  --input '{"ticket_id": "<ticket_id>", "autonomous": <bool>, "skip_to": <phase_or_null>}' \
  --timeout 3600
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it
directly, do not produce prose.

## Post-dispatch: Render results

Parse the node output and display:

```
Ticket Work — <ticket_id>
==========================
Status       : <status>
Phase reached: <phase_reached>
PR URL       : <pr_url or "none">
```

If status is `blocked` or `pending`, display any blocking questions or gates
from the node output. Do not attempt to resolve them inline.

## Error handling

- If `onex run-node node_ticket_work` fails: surface the `SkillRoutingError`
  JSON envelope from stdout/stderr and exit non-zero.
- Do not fall back to inline phase execution, MCP tool calls, or tracker API calls.
  The node is the single source of truth for ticket work logic (A4 amendment).
