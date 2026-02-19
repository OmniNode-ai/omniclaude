# Hook Data Flow Architecture

**Last Updated**: 2026-02-19
**Ticket**: OMN-1980 (agent YAML loading removed from sync path)

---

## Overview

The `UserPromptSubmit` hook is the most complex of the four Claude Code hooks (SessionStart, UserPromptSubmit, PostToolUse, SessionEnd). When a user submits a prompt, the hook runs a pipeline that selects an agent, enriches context, and returns a JSON payload telling Claude which agent to use and what additional context to include. The entire sync path has a 500ms typical budget, with a worst-case of ~15s when all timeouts fire and local delegation is enabled.

This document describes every module in that pipeline, its role, timing classification, and failure behavior.

---

## Complete Flow Diagram

```
Claude Code (stdin JSON)
    {"sessionId": "uuid", "prompt": "user text"}
         │
         ├─────────────────────────────────────────────────────────────┐
         │ [ASYNC, backgrounded immediately — does not count toward budget] │
         │                                                              │
         │  emit_client_wrapper.py → Unix Socket → Emit Daemon         │
         │      │                                                       │
         │      ├─► onex.evt.omniclaude.prompt-submitted.v1            │
         │      │       (100-char redacted preview only)               │
         │      │                                                       │
         │      └─► onex.cmd.omniintelligence.claude-hook-event.v1    │
         │               (full prompt — restricted topic)              │
         └─────────────────────────────────────────────────────────────┘
         │
         ▼ [SYNC — counts toward 500ms budget]
         │
    ┌────┴──────────────────────────────────────────┐
    │  agent_detector.py                            │
    │  Detect automated workflow keywords           │
    │  (parallel, orchestrate, workflow, etc.)      │
    │  Regex matching, <5ms                         │
    └────┬──────────────────────────────────────────┘
         │
         ▼
    ┌────┴──────────────────────────────────────────┐
    │  context_enrichment_runner.py                 │
    │  [if ENABLE_LOCAL_INFERENCE_PIPELINE=true      │
    │   AND ENABLE_LOCAL_ENRICHMENT=true]            │
    │                                               │
    │  Runs in parallel (asyncio.gather):           │
    │    - HandlerSummarizationEnrichment (150ms)   │
    │    - HandlerCodeAnalysisEnrichment (150ms)    │
    │    - HandlerSimilarityEnrichment (150ms)      │
    │  200ms outer timeout, 150ms per-enrichment    │
    │  Token cap: 2000 tokens, priority-based drop  │
    └────┬──────────────────────────────────────────┘
         │
         ▼
    ┌────┴──────────────────────────────────────────┐
    │  route_via_events_wrapper.py                  │
    │  3-tier agent routing (5s timeout)            │
    │                                               │
    │  Tier A: ONEX nodes (USE_ONEX_ROUTING_NODES)  │
    │  Tier B: LLM routing (USE_LLM_ROUTING)        │
    │  Tier C: Fuzzy trigger matching (AgentRouter) │
    │                                               │
    │  Returns: selected_agent + candidates list    │
    │  No-fallback: empty string when no match      │
    └────┬──────────────────────────────────────────┘
         │
         │ [NOTE: Agent YAML loading removed from sync path — OMN-1980]
         │ Claude loads the selected agent's YAML on-demand after
         │ seeing the candidates list in additionalContext.
         │
         ▼
    ┌────┴──────────────────────────────────────────┐
    │  context_injection_wrapper.py                 │
    │  Load learned patterns from PostgreSQL        │
    │  1s timeout, fails silently                   │
    └────┬──────────────────────────────────────────┘
         │
         ▼
    ┌────┴──────────────────────────────────────────┐
    │  pattern_advisory_formatter.py                │
    │  Load pending PatternAdvisory objects         │
    │  (written by PostToolUse compliance path)     │
    │  Reads /tmp/omniclaude-advisory-{uid}/{hash}  │
    │  1s timeout, fails silently                   │
    └────┬──────────────────────────────────────────┘
         │
         ▼
    ┌────┴──────────────────────────────────────────┐
    │  local_delegation_handler.py (optional)       │
    │  [if ENABLE_LOCAL_DELEGATION=true             │
    │   AND ENABLE_LOCAL_INFERENCE_PIPELINE=true]   │
    │                                               │
    │  delegation_orchestrator.py:                  │
    │    1. TaskClassifier.is_delegatable()         │
    │    2. Endpoint selection by intent type       │
    │    3. LLM call (7s timeout)                  │
    │    4. Quality gate (heuristic, <5ms)          │
    │                                               │
    │  If delegated=True: response injected into    │
    │  additionalContext, Claude is bypassed        │
    └────┬──────────────────────────────────────────┘
         │
         ▼
    Output to Claude Code (stdout JSON):
    {
      "hookSpecificOutput": {
        "additionalContext": "<assembled markdown>"
      }
    }
```

---

## Module Roles

### `agent_detector.py`

Scans the prompt with pre-compiled regular expressions for automated-workflow keywords (`parallel`, `orchestrate`, `workflow`, `multi-agent`, etc.). Returns a boolean flag that the shell script uses to adjust behavior for automated vs. interactive sessions. Runs in <5ms.

### `context_enrichment_runner.py`

Runs three enrichment handlers in parallel using `asyncio.gather`. Each handler has a 150ms per-enrichment timeout; all three share a 200ms outer timeout. Any handler that times out or errors produces an empty result. Results are then passed through a token-cap with priority-based drop policy (priority order: summarization > code_analysis > similarity, cap: 2000 tokens). Only active when both `ENABLE_LOCAL_INFERENCE_PIPELINE` and `ENABLE_LOCAL_ENRICHMENT` are true. Failures always exit 0.

Enrichment channels:
- **HandlerSummarizationEnrichment**: Summarizes recent project context.
- **HandlerCodeAnalysisEnrichment**: Analyzes code structure relevant to the prompt.
- **HandlerSimilarityEnrichment**: Retrieves semantically similar past patterns via embeddings.

After applying the token cap, per-enrichment observability events are emitted to `onex.evt.omniclaude.context-enrichment.v1` via `enrichment_observability_emitter.py` (fire-and-forget).

### `route_via_events_wrapper.py`

The routing engine. Runs up to three tiers in sequence, returning the first successful result:

1. **ONEX nodes** (`USE_ONEX_ROUTING_NODES=true`): delegates to `HandlerRoutingDefault` + `HandlerRoutingEmitter` + `HandlerHistoryPostgres`. Emits a structured routing decision event via the emission handler.
2. **LLM routing** (`USE_LLM_ROUTING=true` + `ENABLE_LOCAL_INFERENCE_PIPELINE=true`): calls `HandlerRoutingLlm` with a 100ms budget (LLM_ROUTING_TIMEOUT_S). Health-checks the endpoint first. LatencyGuard enforces P95 SLO of 80ms; opens circuit for 5 minutes on breach.
3. **Fuzzy trigger matching**: `AgentRouter.route()` using compiled regex triggers from agent YAML configs. CONFIDENCE_THRESHOLD=0.5. Returns up to 5 candidates sorted by score.

When no tier succeeds or confidence is below threshold, returns `selected_agent=""` (no fallback — OMN-2228).

Emits `routing.decision` to `onex.evt.omniclaude.routing-decision.v1` after every routing attempt (non-blocking, via daemon).

### `context_injection_wrapper.py`

Queries PostgreSQL for learned patterns associated with the current session and project. Patterns are returned as markdown sections that Claude uses to apply coding standards without being told explicitly. 1-second timeout. When PostgreSQL is unavailable or the query times out, returns empty string and proceeds.

### `pattern_advisory_formatter.py`

Reads and clears the advisory temp file at `/tmp/omniclaude-advisory-{uid}/{session_hash}.json`. Advisories are PatternAdvisory objects written by the PostToolUse compliance path. Formats them as a markdown "## Pattern Advisory" block (max 5 advisories, stale threshold 1 hour). Returns empty string if no advisories.

### `compliance_result_subscriber.py`

Not in the UserPromptSubmit sync path. Runs as a background Kafka subscriber thread (started by SessionStart) that consumes `onex.evt.omniintelligence.compliance-evaluated.v1` and writes PatternAdvisory objects to the temp file. These are picked up by `pattern_advisory_formatter.py` on the next UserPromptSubmit call.

### `local_delegation_handler.py` / `delegation_orchestrator.py`

Optional delegation path. `delegation_orchestrator.py` runs a 5-gate pipeline: feature-flag check, task classification, endpoint selection, LLM call (7s timeout), and a heuristic quality gate (<5ms). If all gates pass, returns the formatted local model response for injection. The quality gate checks minimum response length, absence of refusal indicators in the first 200 characters, and presence of task-type-specific content markers. On any gate failure, returns `delegated=False` and lets Claude handle the prompt normally.

---

## Timing Budget

| Component | Sync Budget | Note |
|-----------|-------------|------|
| `agent_detector` | <5ms | Regex, always fast |
| `context_enrichment_runner` | 200ms max | 200ms outer timeout, 150ms per-enrichment |
| `route_via_events_wrapper` | 5000ms max | LLM routing: ~200ms; fuzzy: <100ms typical |
| `context_injection_wrapper` | 1000ms max | PostgreSQL query with timeout |
| `pattern_advisory_formatter` | <10ms | File read only |
| `delegation_orchestrator` | 8000ms max | 7s LLM call + overhead |
| **Total typical** | **<500ms** | No delegation, services available |
| **Total worst-case** | **~15s** | All timeouts fire + delegation enabled |
| **Total worst-case (no delegation)** | **~7s** | Routing 5s + injection 1s + advisory 1s |

The Kafka emit (dual-emission) is backgrounded and does not count toward any budget.

---

## Output JSON

The hook writes to stdout. Claude Code reads this and injects the `additionalContext` into the prompt context before the model sees it.

```json
{
  "hookSpecificOutput": {
    "additionalContext": "## Agent Selection\n\nSelected: agent-debug (confidence: 0.85)\n\n## Candidates\n- agent-debug (0.85): ...\n- agent-testing (0.60): ...\n\n## Context Patterns\n...\n\n## Pattern Advisory\n..."
  }
}
```

When delegation succeeds, the format changes:

```json
{
  "hookSpecificOutput": {
    "additionalContext": "[Local Model Response - Qwen3-Coder-30B-A3B]\n\n<response text>\n\n---\nDelegated via local model: ..."
  }
}
```

---

## Failure Modes

| Failure | Behavior | Budget Impact |
|---------|----------|---------------|
| Emit daemon down | Events dropped silently, hook continues | None (backgrounded) |
| Kafka unavailable | Daemon drops events after brief buffer | None (backgrounded) |
| Enrichment timeout (200ms) | Empty enrichment context, hook continues | +200ms max |
| Routing timeout (5s) | Returns `selected_agent=""`, hook continues | +5s max |
| Routing confidence below 0.5 | Returns `selected_agent=""`, no agent selected | Typical routing time |
| Context injection timeout (1s) | Empty pattern context, hook continues | +1s max |
| Pattern advisory file missing | Empty advisory block, hook continues | <1ms |
| Delegation LLM timeout (7s) | Returns `delegated=False`, Claude handles prompt | +7s max |
| Delegation quality gate fails | Returns `delegated=False`, Claude handles prompt | <5ms after LLM call |
| PostgreSQL down | Context injection skipped | +1s (timeout) |

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/hooks/lib/agent_detector.py` | Workflow keyword detection |
| `plugins/onex/hooks/lib/context_enrichment_runner.py` | Parallel enrichment pipeline |
| `plugins/onex/hooks/lib/route_via_events_wrapper.py` | 3-tier agent routing |
| `plugins/onex/hooks/lib/context_injection_wrapper.py` | PostgreSQL pattern injection |
| `plugins/onex/hooks/lib/pattern_advisory_formatter.py` | Advisory file read + format |
| `plugins/onex/hooks/lib/compliance_result_subscriber.py` | Background Kafka subscriber |
| `plugins/onex/hooks/lib/local_delegation_handler.py` | Delegation dispatch (legacy) |
| `plugins/onex/hooks/lib/delegation_orchestrator.py` | Delegation with quality gate |
| `plugins/onex/hooks/scripts/user-prompt-submit.sh` | Shell entry point |
| `src/omniclaude/hooks/schemas.py` | Event schemas |
| `src/omniclaude/hooks/topics.py` | Kafka topic definitions |
