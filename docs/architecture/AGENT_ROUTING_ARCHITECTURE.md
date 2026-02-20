# Agent Routing Architecture

**Last Updated**: 2026-02-19
**Tickets**: OMN-1980 (agent YAML removed from sync path), OMN-1893 (routing_path signal), OMN-2273 (LLM routing observability), PR-92 (routing.decision emission)

---

## Overview

Agent routing maps a user prompt to the most appropriate specialized agent YAML definition. The system uses a 3-tier approach that tries progressively simpler methods: ONEX compute nodes, LLM-based classification, and fuzzy trigger matching. Each tier can be independently enabled or disabled via feature flags. When no tier produces a confident match, routing returns an empty string — there is no default fallback agent.

All routing runs in the UserPromptSubmit sync path and contributes to the 500ms typical budget. The 5-second hard timeout is the safety net, not the expected case.

---

## Routing Pipeline Diagram

```
route_via_events(prompt, correlation_id, timeout_ms=5000)
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│  TIER A: ONEX Routing Nodes                                │
│  Feature flag: USE_ONEX_ROUTING_NODES=true                 │
│                                                            │
│  HandlerRoutingDefault.compute_routing(request)            │
│      + HandlerRoutingEmitter.emit_routing_decision(...)    │
│      + HandlerHistoryPostgres (cached stats, 5-min TTL)    │
│                                                            │
│  If result returned within timeout_ms → use it, STOP       │
│  If None or timeout → fall through to Tier B               │
└────────────────────────────────────────────────────────────┘
         │ (fall-through if ONEX unavailable or flag off)
         ▼
┌────────────────────────────────────────────────────────────┐
│  TIER B: LLM Routing                                       │
│  Feature flags: ENABLE_LOCAL_INFERENCE_PIPELINE=true       │
│                 USE_LLM_ROUTING=true                       │
│  Also gated by: LatencyGuard.is_enabled()                  │
│                                                            │
│  1. Resolve LLM URL from LocalLlmEndpointRegistry          │
│     Priority: ROUTING → GENERAL → REASONING → CODE_ANALYSIS│
│                                                            │
│  2. Health-check endpoint (GET /health, 85ms timeout)      │
│                                                            │
│  3. Build ModelAgentDefinition list from AgentRouter       │
│                                                            │
│  4. HandlerRoutingLlm.compute_routing(request)             │
│     Timeout: LLM_ROUTING_TIMEOUT_S (default 100ms)         │
│                                                            │
│  5. Background thread: record LLM vs fuzzy agreement       │
│     (feeds LatencyGuard auto-disable gate)                  │
│                                                            │
│  If result returned → use it, emit LLM decision, STOP      │
│  If None, unhealthy, or timeout → fall through to Tier C   │
└────────────────────────────────────────────────────────────┘
         │ (fall-through if LLM unavailable, flag off, or guard open)
         ▼
┌────────────────────────────────────────────────────────────┐
│  TIER C: Fuzzy Trigger Matching                            │
│  Always available (no feature flag required)               │
│                                                            │
│  AgentRouter.route(prompt, max_recommendations=5)          │
│  Produces RoutingRecommendation list sorted by score       │
│                                                            │
│  Confidence threshold: CONFIDENCE_THRESHOLD = 0.5          │
│  Below threshold → selected_agent = "" (no selection)      │
│                                                            │
│  Returns top match + up to 5 candidates                    │
└────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│  Timeout enforcement                                       │
│  if latency_ms > timeout_ms:                               │
│    selected_agent = ""  (force no-match)                   │
│    candidates = []                                         │
│    reasoning = "Routing timeout"                           │
└────────────────────────────────────────────────────────────┘
         │
         ▼
  Emit routing.decision → onex.evt.omniclaude.routing-decision.v1
  (non-blocking, via emit daemon)
         │
         ▼
  Return dict:
  {
    "selected_agent": "agent-debug" | "",
    "confidence": 0.85,
    "candidates": [{"name": ..., "score": ..., "description": ..., "reason": ...}],
    "reasoning": "...",
    "routing_method": "local" | "event_based" | "fallback",
    "routing_policy": "trigger_match" | "explicit_request" | "fallback_default",
    "routing_path": "local" | "event" | "hybrid",
    "latency_ms": 15,
    "domain": "debugging",
    "purpose": "..."
  }
```

---

## Tier C: Fuzzy Trigger Matching in Detail

The fuzzy matcher (`AgentRouter`) loads all agent YAML configs and indexes their `activation_patterns.explicit_triggers` and `context_triggers`. For each routing request it scores every agent and returns the top N candidates.

Matching works through compiled regex patterns derived from the trigger strings. The confidence score is a composite that includes trigger match strength, pattern specificity, and historical accuracy hints (when ONEX nodes provide stats).

**CONFIDENCE_THRESHOLD = 0.5**

Agents with a top score below 0.5 are not selected — `selected_agent` is returned as `""`. This is the "no-fallback" mode introduced to replace the old behavior of defaulting to `polymorphic-agent` on every miss. When `selected_agent=""`, Claude receives the candidates list but no pre-selected agent; it uses the candidates as hints to make its own semantic selection.

See `docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md` for detailed threshold tuning notes and the rationale for 0.5 as the cutoff.

---

## Candidate List Injection (OMN-1980)

Before OMN-1980, the routing hook loaded the selected agent's YAML and injected it synchronously. This added up to 1 second to the hook's sync path (YAML load timeout). OMN-1980 removed this: the hook now passes only the **candidates list** to Claude. Claude reads the list, makes a semantic selection, and loads the YAML on-demand.

The candidates list in the routing result:
```json
[
  {"name": "agent-debug", "score": 0.85, "description": "Debug and troubleshoot", "reason": "Exact match: 'debug'"},
  {"name": "agent-testing", "score": 0.60, "description": "Write and run tests", "reason": "Fuzzy match: 'test'"}
]
```

This list is formatted by the shell script into the `additionalContext` markdown. Claude selects from this list — it is not a binding decision but a strong recommendation.

---

## Routing Semantics: Three Distinct Fields

Every routing result includes three fields that together describe the decision:

| Field | Answers | Values |
|-------|---------|--------|
| `routing_method` | HOW routing ran | `local`, `event_based`, `fallback` |
| `routing_policy` | WHY this path was chosen | `trigger_match`, `explicit_request`, `fallback_default`, `safety_gate`, `cost_gate` |
| `routing_path` | WHAT canonical outcome | `local`, `event`, `hybrid` |

`routing_path` follows this logic:
- `event_attempted=False` → `"local"` (never tried event bus)
- `event_attempted=True` AND `routing_method=event_based` → `"event"`
- `event_attempted=True` AND `routing_method=fallback` → `"hybrid"` (tried event, fell back)

These three fields feed downstream analytics and the observability dashboard without conflating the mechanism, the policy, and the outcome.

---

## No-Fallback Mode

Prior to the no-fallback design, every routing miss fell back to `polymorphic-agent`. This had two problems: (1) `polymorphic-agent` was selected even when irrelevant, polluting routing metrics, and (2) it suppressed the signal that no good match existed.

Current behavior: `DEFAULT_AGENT = ""` (empty string). When confidence is below 0.5 or no triggers match, `selected_agent` is `""`. The shell script detects this and omits the agent selection banner from `additionalContext`. Claude receives the candidates list and falls back to its own judgment.

---

## LatencyGuard: Circuit Breaker for LLM Routing

`LatencyGuard` is a singleton that enforces two gates before allowing LLM routing to proceed:

**P95 SLO gate**: Rolling window of the last 100 LLM routing call latencies. If P95 exceeds 80ms, the circuit opens for 5 minutes (COOLDOWN_SECONDS=300). Requires at least 10 samples before tripping (MIN_SAMPLES_FOR_TRIP=10).

**Agreement rate gate**: Rolling 3-day window of LLM vs. fuzzy-match agreement observations. If the agreement rate falls below 60% with at least 20 observations, LLM routing is disabled. Agreement is recorded in a background daemon thread (`llm-fuzzy-agreement`) so that the fuzzy shadow run does not add to the sync path latency.

```
LatencyGuard.is_enabled()
    │
    ├─ circuit open (P95 SLO breach, within cooldown)? → False
    ├─ agreement_rate < 0.60 (with >= 20 samples)? → False
    └─ otherwise → True
```

When `is_enabled()` returns `False`, `_use_llm_routing()` returns `False` and Tier B is skipped entirely.

---

## Observability Events

Every routing decision emits at least one Kafka event. LLM routing emits two:

| Event | Topic | When |
|-------|-------|------|
| `routing.decision` | `onex.evt.omniclaude.routing-decision.v1` | Every routing call (all tiers) |
| `llm.routing.decision` | `onex.evt.omniclaude.llm-routing-decision.v1` | LLM tier succeeds |
| `llm.routing.fallback` | `onex.evt.omniclaude.llm-routing-fallback.v1` | LLM tier returns None |

All emissions are non-blocking: `emit_event()` is called after the routing result is assembled and returns immediately. Emission failure is logged at DEBUG level and never surfaces to the caller.

The `routing.decision` payload includes `prompt_preview` (100-char, redacted) to keep it safe for the broad-access `onex.evt.*` topic.

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| ONEX nodes unavailable (import error) | Falls through to Tier B silently |
| ONEX routing exceeds timeout_ms | Discards result, falls through to Tier B |
| LLM endpoint unhealthy (health check fails) | Returns None, falls through to Tier C |
| LLM routing timeout (LLM_ROUTING_TIMEOUT_S) | Returns None, falls through to Tier C; latency recorded with guard |
| LLM hallucinated agent name (not in registry) | Logs warning, uses result anyway with empty domain/purpose |
| LatencyGuard circuit open | Skips Tier B entirely, proceeds to Tier C |
| AgentRouter unavailable (import error) | Returns fallback dict: `selected_agent=""`, `confidence=0.0` |
| AgentRouter throws exception | Catches exception, returns fallback |
| Overall timeout (timeout_ms exceeded) | Forces `selected_agent=""`, clears candidates |
| Empty or non-string prompt | Returns immediately with `selected_agent=""`, logs warning |

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/hooks/lib/route_via_events_wrapper.py` | Main routing orchestrator |
| `plugins/onex/hooks/lib/agent_router.py` | Tier C fuzzy trigger matcher |
| `plugins/onex/hooks/lib/latency_guard.py` | P95 SLO and agreement rate circuit breaker |
| `src/omniclaude/nodes/node_agent_routing_compute/handler_routing_default.py` | Tier A ONEX compute handler |
| `src/omniclaude/nodes/node_agent_routing_compute/handler_routing_llm.py` | Tier B LLM routing handler |
| `src/omniclaude/nodes/node_routing_emission_effect/handler_routing_emitter.py` | Tier A routing event emitter |
| `src/omniclaude/config/model_local_llm_config.py` | LLM endpoint registry |
| `plugins/onex/agents/configs/*.yaml` | Agent definitions with `activation_patterns` |
| `docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md` | Threshold tuning rationale |
