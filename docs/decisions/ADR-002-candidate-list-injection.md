# ADR-002: Remove YAML Loading from Synchronous Hook Path

**Date**: 2026-02-19
**Status**: Accepted
**Ticket**: OMN-1980, PR #138

## Context

Each UserPromptSubmit hook invocation was loading and parsing the selected agent's YAML file
synchronously, as part of the hook's blocking execution path. The sequence was:

1. Route prompt to best-matching agent
2. Load and parse that agent's YAML from disk
3. Inject agent capabilities into the prompt context
4. Return the enriched context to Claude

This worked correctly but added measurable latency on every prompt submission. Agent YAML files
range from 2KB to 15KB and include regex patterns, capability lists, and trigger definitions.
Parsing 50+ YAML files on each hook invocation was wasteful — only one agent is ever selected per
prompt.

**Alternatives considered**:

- **In-memory YAML cache**: Pre-load all agent YAMLs at SessionStart and cache them. Rejected
  because it adds ~200ms to session start and wastes memory for agents never selected in that
  session.
- **Lazy load with LRU cache**: Load on first selection, cache in process memory. Rejected because
  the hook runs as a subprocess (not a persistent process), so the cache is lost between
  invocations.
- **Candidate list injection**: Return a ranked list of candidate agents with confidence scores;
  let Claude select and load the winner's YAML on-demand. Accepted.

## Decision

Move to candidate list injection. The hook now returns a JSON list of candidate agents with
confidence scores rather than a single deterministic selection with fully-loaded YAML content.
Claude selects the winning agent from the candidate list and loads that agent's YAML on-demand
after the hook exits.

The YAML loading step is entirely removed from the hook's synchronous path. The hook's job is
limited to: classify the prompt, score candidates, return the ranked list.

## Consequences

**Positive**:
- Hook latency reduced significantly (YAML parse time eliminated from sync path).
- Hook output is smaller — a compact JSON candidate list rather than expanded YAML content.
- Decouples routing accuracy from YAML load performance; the two can be tuned independently.
- Claude can apply its own judgment when selecting from close-scoring candidates.

**Negative / trade-offs**:
- Claude is now responsible for selecting from the candidate list rather than receiving a single
  deterministic result. Edge cases where two candidates score similarly may produce inconsistent
  selections across sessions.
- The "winning agent" is determined by Claude's interpretation of the candidate list, not by the
  routing service alone. Routing and selection are no longer a single atomic decision.
- Debugging routing failures requires reasoning about both the hook's scoring and Claude's
  subsequent candidate selection.

## Implementation

Key files:
- `plugins/onex/hooks/lib/route_via_events_wrapper.py` — returns candidate list instead of single
  agent selection; YAML loading removed
- `plugins/onex/hooks/lib/agent_detector.py` — classifies prompt type, feeds into candidate
  scoring
