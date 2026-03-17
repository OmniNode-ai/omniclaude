---
name: generate_tcb
description: Generate an Intent-Warmed Ticket Context Bundle (TCB) for a Linear ticket with grounded evidence
version: 1.0.0
level: advanced
debug: false
category: workflow
---

# generate-tcb

## Description

Generate an Intent-Warmed Ticket Context Bundle (TCB) for a Linear ticket.
Fetches the ticket, normalizes intent, retrieves grounded evidence (files, PRs, tests,
patterns), scores and ranks candidates, assembles the bundle, and posts it as a ticket
comment plus stores JSON locally.

## When to Use

- Automatically after `linear/create-ticket`
- Manually: `/generate-tcb OMN-XXXX`
- In ticket-pipeline Phase 0.5 (decision_context_load) when bundle is absent or stale

## Inputs

- `ticket_id` -- required (e.g., OMN-1234)
- `epic_id` -- optional; if provided, uses epic's repo scope as additional signal
- `force_regenerate` -- optional bool; if true, regenerate even if fresh bundle exists

## Outputs

- JSON artifact: `~/.claude/tcb/{ticket_id}/bundle.json` (ModelTicketContextBundle serialized)
- Ticket comment: Markdown summary posted to Linear ticket
- Stdout: "TCB generated for {ticket_id}: {entrypoint_count} entrypoints, {test_count} tests, {pattern_count} patterns"

## Size Limits (Hard Caps)

- Entrypoints: max 10 (top 10 by score)
- Related PRs/commits: max 10
- Tests to run: max 15
- Patterns: max 10
- Constraints: max 20
- TTL: 7 days default

## Authoritative Behavior

See `prompt.md` for the full step-by-step execution protocol.
