# ADR-006: Three-Tier Agent Routing (LLM → Fuzzy → Explicit)

**Date**: 2026-02-19
**Status**: Accepted
**Ticket**: OMN-2259, OMN-2265, PR #158, PR #160

## Context

Agent routing must accurately match user prompts to the most appropriate agent from a catalog of
50+ specialized agents. Two naive approaches fail at production scale:

**Keyword/explicit-only routing**: Each agent declares keyword triggers; prompts are matched
against them. Fast and deterministic, but misses semantically similar prompts that don't contain
the exact trigger words. A user asking "help me design my HTTP API" should route to
`api-architect` even if the trigger list says "api design" and "openapi" — keyword matching may
miss it.

**LLM-only routing**: Route every prompt through an LLM for semantic classification. Accurate but
too slow — an LLM call adds 200-400ms to every prompt submission, pushing the worst-case hook
latency well beyond the 500ms budget when combined with context injection and other sync-path work.

Neither approach alone meets the accuracy and latency requirements simultaneously.

**Alternatives considered**:

- **Two-tier (explicit + fuzzy only)**: Use explicit triggers first, then fall back to fuzzy
  matching. No LLM in the path. Rejected — fuzzy matching is more accurate than pure keyword
  matching but still misses semantic synonyms and intent-driven prompts.
- **Two-tier (LLM + explicit fallback)**: Try LLM first; fall back to explicit triggers if LLM
  times out. Rejected — explicit triggers are a subset of fuzzy matching; a separate explicit
  tier adds complexity without meaningful benefit over just extending the fuzzy matcher.
- **Three-tier (explicit → LLM → fuzzy)**: Fast explicit check first, then LLM for misses, then
  fuzzy as LLM fallback. Accepted.

## Decision

Implement three-tier routing executed in priority order:

**Tier 1 — Explicit trigger matching** (fast, deterministic):
- Each agent YAML declares `activation_patterns.explicit_triggers` — exact string matches.
- Checked first. If a prompt contains an exact trigger phrase, route immediately without LLM.
- Latency: <5ms. Covers high-confidence, unambiguous cases.

**Tier 2 — LLM-based semantic routing** (accurate, ~200ms):
- Prompt is classified by a local LLM at `LLM_CODER_FAST_URL` (Qwen3-14B-AWQ, 40K context).
- The model returns agent name + confidence score.
- Used when no explicit trigger matched. Covers semantic synonyms and intent-driven prompts.
- Latency: ~200ms typical. Has a 5-second timeout; falls through to Tier 3 on timeout.

**Tier 3 — Fuzzy TriggerMatcher fallback** (fast, covers LLM failures):
- Fuzzy string matching against all agent triggers using configurable similarity thresholds.
- Used when LLM is unavailable, times out, or returns below the confidence threshold.
- Latency: <20ms. Ensures graceful degradation when the LLM endpoint is unreachable.
- Threshold configuration documented in `docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md`.

All three tiers produce a scored candidate list (see ADR-002); no tier produces a hard selection.

## Consequences

**Positive**:
- Routing accuracy is significantly better than explicit-only routing without sacrificing the
  500ms budget for the common case (Tier 1 hits).
- Graceful degradation — LLM unavailability falls through to fuzzy matching automatically.
  Users experience reduced accuracy, not errors.
- The three tiers are independently observable; metrics can show which tier is handling what
  fraction of traffic.
- Tier 2 uses `LLM_CODER_FAST_URL` (mid-tier model), not the full coder model — cost-efficient.

**Negative / trade-offs**:
- Routing behavior depends on external LLM availability. When the LLM endpoint is degraded,
  accuracy silently drops to fuzzy-matching levels. Operators must monitor Tier 2 usage rates
  to detect this.
- Three-tier logic is more complex than a single-strategy approach. The code path has more
  branches and the interaction between tiers requires careful testing.
- Fuzzy threshold tuning (`docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md`) must be revisited
  when new agents are added — a new agent may shift the similarity landscape enough to cause
  misroutes.

## Implementation

Key files:
- `plugins/onex/hooks/lib/route_via_events_wrapper.py` — three-tier dispatch logic, timeout
  handling, candidate list assembly
- `src/omniclaude/config/model_local_llm_config.py` — `LLM_CODER_FAST_URL` and LLM routing
  configuration
- `plugins/onex/agents/configs/*.yaml` — per-agent `activation_patterns.explicit_triggers` and
  `context_triggers`
- `docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md` — fuzzy threshold specifications
