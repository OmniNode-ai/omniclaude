# ADR-003: Fail-Fast Routing — No Silent Fallback to polymorphic-agent

**Date**: 2026-02-19
**Status**: Accepted
**Ticket**: PR #173

## Context

The original routing logic always fell back to `polymorphic-agent` when no candidate matched the
prompt above the confidence threshold. The behavior was:

```
Route prompt → no match above threshold → silently return polymorphic-agent
```

This created an observability blind spot. From the outside, two situations looked identical:

1. The prompt was correctly routed to `polymorphic-agent` because it was a general-purpose task.
2. The routing service failed (timeout, empty candidates, all below threshold), so it fell back to
   `polymorphic-agent`.

There was no way to distinguish a successful routing decision from a silent failure. This made
routing quality metrics unreliable — the denominator included both genuine polly selections and
masked failures.

**Alternatives considered**:

- **Keep silent fallback, add a metadata flag**: Attach a `fallback_reason` field to the response
  when falling back. Rejected because downstream consumers would need to handle the flag
  inconsistently, and the hook output format would become ambiguous.
- **Fail-fast with exit code 1**: Return a non-zero exit to block the prompt when routing fails.
  Rejected — hooks must exit 0 on infrastructure failure per the repository invariants. Blocking
  Claude Code is never acceptable.
- **Explicit no-match signal**: Return a structured no-match result that Claude and observability
  systems can distinguish from a genuine polly selection. Accepted.

## Decision

When the routing service finds no candidate above the confidence threshold, the hook now returns
an explicit no-match signal rather than silently substituting `polymorphic-agent`. The no-match
result includes:

- `matched: false`
- `reason: "no_candidate_above_threshold"` (or `"routing_timeout"`, `"empty_candidates"`, etc.)
- No agent selection

Claude interprets a no-match result and defaults to `polymorphic-agent` as a consequence of no
match, not as a routing decision. The distinction is preserved in observability events.

## Consequences

**Positive**:
- Routing failures are visible. Operators can monitor the no-match rate separately from
  genuine polymorphic-agent selections.
- Routing quality metrics become trustworthy — the denominator excludes masked failures.
- The reason for a no-match is recorded (`routing_timeout` vs `no_candidate` vs
  `empty_candidates`), enabling targeted diagnosis.
- "Routed to polly because it's the right agent" is distinguishable from "fell through".

**Negative / trade-offs**:
- Prompts with no good match now produce a different hook output shape than prompts with a match.
  Claude and any downstream consumers must handle both shapes.
- Operators who relied on routing metrics that included silent fallbacks will see apparent
  metric changes at deploy time — the real routing accuracy was always lower than reported.

## Implementation

Key files:
- `plugins/onex/hooks/lib/route_via_events_wrapper.py` — explicit no-match return path; fallback
  substitution removed
