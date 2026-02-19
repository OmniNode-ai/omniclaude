# ADR-005: Local LLM Delegation with 2-Clean-Run Quality Gate

**Date**: 2026-02-19
**Status**: Accepted
**Ticket**: OMN-2281, PR #177

## Context

A significant portion of prompts submitted to Claude Code are routine code tasks — formatting,
renaming, generating boilerplate, simple transformations — that do not require a frontier cloud
model. Routing these to a local LLM would reduce latency and cost. However, local LLMs produce
lower-quality output at a higher rate than cloud models, and silently accepting degraded output
would harm user trust.

The problem has two parts:

1. **Classification**: Which tasks are suitable for local delegation? Classification must be fast
   (within the UserPromptSubmit budget) and conservative — false positives (delegating tasks that
   need the cloud model) are worse than false negatives.
2. **Quality gate**: How do we accept local LLM output confidently? A single run may succeed by
   chance; we need a signal that the result is stable.

**Alternatives considered**:

- **No quality gate, single run**: Accept first local LLM output. Rejected — local model output
  is non-deterministic; a single successful run does not indicate stable quality.
- **Human review step**: Route local output to human review before accepting. Rejected — eliminates
  the latency benefit of local delegation.
- **Statistical sampling (N runs, majority vote)**: Run the task N times, accept the majority
  result. Rejected — expensive in tokens and time; majority vote requires semantic comparison of
  outputs, which is its own hard problem.
- **2 consecutive clean runs**: Run the task twice; accept only if both runs pass a quality check.
  Accepted — two consecutive clean runs provide high confidence in stability without N-run cost.

## Decision

Add a delegation orchestrator that implements a three-step delegation pipeline:

**Step 1 — Classification** (`task_classifier.py`): Determines if the incoming task is suitable
for local delegation using a lightweight heuristic classifier. Tasks classified as non-delegatable
pass through to the standard cloud routing path immediately.

**Step 2 — Local dispatch** (`local_delegation_handler.py`): Routes delegatable tasks to the
appropriate local LLM endpoint based on task type and estimated token count. Uses
`LLM_CODER_FAST_URL` for most code tasks; falls back gracefully if the endpoint is unavailable.

**Step 3 — Quality gate** (`delegation_orchestrator.py`): Requires 2 consecutive clean runs
before accepting the result. "Clean" is defined by a rubric applied to the output (no error
markers, output length within expected range, structural validity for the task type). If either
run fails the rubric, the result is discarded and the task is re-routed to the cloud path.

Delegation is disabled by default and must be explicitly enabled via environment configuration.

## Consequences

**Positive**:
- Reduces cloud LLM calls for routine tasks that local models handle well.
- The 2-clean-run gate prevents degraded outputs from reaching users silently.
- Graceful fallback — if local dispatch fails or either run fails the gate, the task routes to the
  cloud path with no user-visible error.
- Quality gate failure rate is a useful metric for monitoring local model health.

**Negative / trade-offs**:
- Worst-case latency increases significantly. The delegation path adds up to ~8 seconds to
  UserPromptSubmit (classification + 2 local runs + rubric evaluation). This exceeds the 500ms
  typical budget but is within the documented 15s worst-case ceiling.
- The classification heuristic has false negatives — tasks that could be delegated may not be
  classified as delegatable. This is intentional conservatism.
- Must be explicitly enabled (`ENABLE_DELEGATION=true`). Operators must opt in and monitor
  delegation quality metrics before relying on it for production traffic.

## Implementation

Key files:
- `plugins/onex/hooks/lib/task_classifier.py` — lightweight heuristic classification
- `plugins/onex/hooks/lib/local_delegation_handler.py` — local LLM dispatch and response handling
- `plugins/onex/hooks/lib/delegation_orchestrator.py` — 2-clean-run gate and fallback logic
