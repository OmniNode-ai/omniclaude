# LLM Routing Architecture

**Last Updated**: 2026-02-19
**Tickets**: OMN-2273 (LLM routing observability), OMN-2271 (delegation dispatch), OMN-2267 (enrichment pipeline)

---

## Overview

The `LocalLlmEndpointRegistry` is the central configuration hub for all local LLM endpoints used by omniclaude. Every feature that calls a local model — agent routing, context enrichment, and local delegation — queries the registry to resolve which endpoint to use for a given task type. The registry reads endpoint URLs from environment variables and provides priority-ordered lookup by `LlmEndpointPurpose`.

This document describes the registry itself, how each feature selects endpoints, and how LLM routing integrates with the agent routing pipeline.

---

## Registry Diagram

```
Environment Variables
    LLM_CODER_URL=http://<llm-coder-host>:8000
    LLM_CODER_FAST_URL=http://<llm-fast-host>:8001
    LLM_EMBEDDING_URL=http://<llm-embedding-host>:8100
    LLM_DEEPSEEK_R1_URL=http://<llm-reasoning-host>:8101
    LLM_QWEN_72B_URL=...
    ...
         │
         ▼
LocalLlmEndpointRegistry (pydantic-settings BaseSettings)
    │
    │  _endpoint_configs (cached_property)
    │  Builds list of LlmEndpointConfig for all non-None URLs
    │
    ├── LlmEndpointPurpose.ROUTING
    │     → llm_coder_fast_url (Qwen3-14B-AWQ, RTX 4090, 40K ctx, priority=9)
    │
    ├── LlmEndpointPurpose.CODE_ANALYSIS
    │     → llm_coder_url (Qwen3-Coder-30B-A3B, RTX 5090, 64K ctx, priority=9)
    │
    ├── LlmEndpointPurpose.EMBEDDING
    │     → llm_embedding_url (Qwen3-Embedding-8B-4bit, M2 Ultra, priority=9)
    │
    ├── LlmEndpointPurpose.REASONING
    │     → llm_qwen_72b_url (Qwen2.5-72B, priority=8)
    │     → llm_deepseek_r1_url (DeepSeek-R1-Distill, priority=7)
    │     [highest priority returned by get_endpoint()]
    │
    ├── LlmEndpointPurpose.GENERAL
    │     → llm_deepseek_lite_url (DeepSeek-V2-Lite, priority=3)
    │     → llm_qwen_14b_url (Qwen2.5-14B, priority=6)
    │
    ├── LlmEndpointPurpose.FUNCTION_CALLING
    │     → llm_function_url (Qwen2.5-7B, priority=5)
    │
    └── LlmEndpointPurpose.VISION
          → llm_vision_url (Qwen2-VL, priority=9)
```

---

## Endpoint Inventory

| Environment Variable | Model | Purpose | Hardware | Priority |
|---------------------|-------|---------|----------|----------|
| `LLM_CODER_URL` | Qwen3-Coder-30B-A3B-Instruct | `CODE_ANALYSIS` | RTX 5090 (64K ctx) | 9 |
| `LLM_CODER_FAST_URL` | Qwen3-14B-AWQ | `ROUTING` | RTX 4090 (40K ctx) | 9 |
| `LLM_EMBEDDING_URL` | Qwen3-Embedding-8B-4bit | `EMBEDDING` | M2 Ultra | 9 |
| `LLM_QWEN_72B_URL` | Qwen2.5-72B | `REASONING` | M2 Ultra | 8 |
| `LLM_DEEPSEEK_R1_URL` | DeepSeek-R1-Distill | `REASONING` | M2 Ultra (hot-swap) | 7 |
| `LLM_QWEN_14B_URL` | Qwen2.5-14B | `GENERAL` | M2 Pro | 6 |
| `LLM_FUNCTION_URL` | Qwen2.5-7B | `FUNCTION_CALLING` | RTX 4090 (hot-swap) | 5 |
| `LLM_DEEPSEEK_LITE_URL` | DeepSeek-V2-Lite | `GENERAL` | RTX 4090 (hot-swap) | 3 |
| `LLM_VISION_URL` | Qwen2-VL | `VISION` | M2 Ultra | 9 |

The `ROUTING` purpose is specifically mapped to `LLM_CODER_FAST_URL` (mid-tier, 40K context) because agent routing classification needs fast responses and moderate context, not the full-context coder model. This avoids wasting RTX 5090 capacity on routing.

---

## LLM Routing Integration with Agent Routing

When `USE_LLM_ROUTING=true` and `ENABLE_LOCAL_INFERENCE_PIPELINE=true`, the agent routing pipeline (Tier B in `route_via_events_wrapper.py`) calls a local LLM to classify the prompt against the agent registry. This is how the endpoint selection works:

```
_get_llm_routing_url()
    │
    │  registry = LocalLlmEndpointRegistry()
    │
    ├─ try ROUTING purpose → llm_coder_fast_url (primary choice)
    ├─ try GENERAL purpose → llm_qwen_14b_url or llm_deepseek_lite_url (fallback)
    ├─ try REASONING purpose → llm_qwen_72b_url or llm_deepseek_r1_url (fallback)
    └─ try CODE_ANALYSIS purpose → llm_coder_url (last resort fallback)

    Returns (url, model_name) tuple or None
```

The fallback chain means LLM routing works even if the dedicated routing endpoint is not configured, by falling back to any available general-purpose or reasoning model.

**Timeout for LLM routing**: `LLM_ROUTING_TIMEOUT_S` (default: 100ms). The health check gets 85% of this value (`_LLM_HEALTH_CHECK_TIMEOUT_S`). Two sequential async calls (health check + routing) means worst-case is ~200ms before falling back to fuzzy matching.

---

## Feature-to-Endpoint Mapping

Each feature that uses local inference resolves its endpoint from the registry at call time:

### Agent Routing (Tier B)

```
Purpose resolution order:
  ROUTING → GENERAL → REASONING → CODE_ANALYSIS

Typical endpoint: LLM_CODER_FAST_URL (Qwen3-14B-AWQ, RTX 4090)
Timeout: LLM_ROUTING_TIMEOUT_S (default 100ms)
```

### Context Enrichment

The enrichment handlers resolve their own endpoints internally (implemented in `omnibase_infra`). They use:
- **Summarization**: inference endpoint (typically `LLM_CODER_FAST_URL`)
- **Code Analysis**: inference endpoint (typically `LLM_CODER_FAST_URL`)
- **Similarity**: embedding endpoint (`LLM_EMBEDDING_URL`)

### Local Delegation (Orchestrator)

```
Intent → Purpose → Environment Variable
─────────────────────────────────────────────────
document  → REASONING       → LLM_QWEN_72B_URL (preferred) or LLM_DEEPSEEK_R1_URL
test      → CODE_ANALYSIS   → LLM_CODER_URL (Qwen3-Coder-30B-A3B, RTX 5090)
research  → CODE_ANALYSIS   → LLM_CODER_URL (Qwen3-Coder-30B-A3B, RTX 5090)

Timeout: 7 seconds (_LLM_CALL_TIMEOUT_S)
Max prompt: 8000 chars (truncated with notice)
Max tokens: 2048, temperature: 0.3
```

---

## Latency Budgets by Endpoint

| Purpose | Endpoint | Max Latency | Configured Via |
|---------|----------|------------|----------------|
| ROUTING | `LLM_CODER_FAST_URL` | `LLM_CODER_FAST_MAX_LATENCY_MS` (default 1000ms) | env |
| CODE_ANALYSIS | `LLM_CODER_URL` | `LLM_CODER_MAX_LATENCY_MS` (default 2000ms) | env |
| EMBEDDING | `LLM_EMBEDDING_URL` | `LLM_EMBEDDING_MAX_LATENCY_MS` (default 1000ms) | env |
| GENERAL | various | `LLM_QWEN_14B_MAX_LATENCY_MS` (default 5000ms) | env |
| REASONING | `LLM_QWEN_72B_URL` | `LLM_QWEN_72B_MAX_LATENCY_MS` (default 10000ms) | env |
| VISION | `LLM_VISION_URL` | `LLM_VISION_MAX_LATENCY_MS` (default 5000ms) | env |

These latency budgets are stored in the `LlmEndpointConfig` objects but are not currently enforced at the registry level — they serve as documentation and as SLO hints for the LatencyGuard circuit breaker in the routing path.

---

## Observability Events

LLM routing emits two distinct event types to Kafka (via the emit daemon):

### `llm.routing.decision` → `onex.evt.omniclaude.llm-routing-decision.v1`

Emitted when LLM routing succeeds. Contains determinism audit fields for comparing LLM vs. fuzzy matching agreement:

```json
{
  "session_id": "uuid",
  "correlation_id": "uuid",
  "selected_agent": "agent-debug",
  "llm_confidence": 0.87,
  "llm_latency_ms": 84,
  "fallback_used": false,
  "model_used": "Qwen/Qwen3-14B-AWQ",
  "fuzzy_top_candidate": null,
  "llm_selected_candidate": "agent-debug",
  "agreement": false,
  "routing_prompt_version": "v1.2"
}
```

Note: `agreement` is always `false` at emission time because the background agreement thread runs after this call. The actual agreement observation is recorded with `LatencyGuard.record_agreement()` and tracked separately.

### `llm.routing.fallback` → `onex.evt.omniclaude.llm-routing-fallback.v1`

Emitted when LLM routing returns `None` (unhealthy endpoint, timeout, or any error), causing the pipeline to fall through to fuzzy matching:

```json
{
  "session_id": "uuid",
  "correlation_id": "uuid",
  "fallback_reason": "LLM routing returned None",
  "llm_url": null,
  "routing_prompt_version": "v1.2"
}
```

Both events are emitted non-blocking (fire-and-forget). Emission failures are logged at DEBUG level and swallowed.

---

## Model Name Configuration

Each endpoint has a corresponding `_MODEL_NAME` environment variable. These control the `"model"` field sent in the `/v1/chat/completions` request body. Defaults match the actual deployed model names:

```
LLM_CODER_MODEL_NAME        → "Qwen3-Coder-30B-A3B-Instruct"
LLM_CODER_FAST_MODEL_NAME   → "Qwen/Qwen3-14B-AWQ"
LLM_EMBEDDING_MODEL_NAME    → "Qwen3-Embedding-8B-4bit"
LLM_QWEN_72B_MODEL_NAME     → "Qwen2.5-72B"
LLM_DEEPSEEK_R1_MODEL_NAME  → "DeepSeek-R1-Distill"
LLM_QWEN_14B_MODEL_NAME     → "Qwen2.5-14B"
```

Model names must be non-empty and non-whitespace (validated by `validate_model_name_not_whitespace()`). Setting a model name to whitespace-only is rejected at construction time.

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| No endpoint configured for purpose | `get_endpoint()` returns `None`; caller falls back or skips |
| URL environment variable not set | Field is `None`, endpoint excluded from `_endpoint_configs` |
| Model name is whitespace-only | `ValueError` at `LocalLlmEndpointRegistry()` construction |
| LLM health check fails | LLM routing returns `None`, falls through to fuzzy matching |
| LLM routing timeout | `None` returned, latency recorded with LatencyGuard |
| LatencyGuard circuit open | `_use_llm_routing()` returns `False`, LLM routing skipped |
| Agreement rate too low | `LatencyGuard.is_enabled()` returns `False`, LLM routing skipped |
| `pydantic-settings` .env not found | Only env vars in `os.environ` are loaded; no error |
| `model_copy()` on registry | Stale `_endpoint_configs` cache (documented anti-pattern; do not use) |
| Delegation endpoint missing | `_select_handler_endpoint()` returns `None`, `delegated=False` |

---

## Key Files

| File | Role |
|------|------|
| `src/omniclaude/config/model_local_llm_config.py` | `LocalLlmEndpointRegistry`, `LlmEndpointPurpose`, `LlmEndpointConfig` |
| `plugins/onex/hooks/lib/route_via_events_wrapper.py` | LLM routing pipeline integration (`_route_via_llm`, `_get_llm_routing_url`) |
| `plugins/onex/hooks/lib/latency_guard.py` | P95 SLO and agreement rate circuit breaker |
| `plugins/onex/hooks/lib/delegation_orchestrator.py` | Delegation endpoint selection (`_select_handler_endpoint`) |
| `src/omniclaude/hooks/topics.py` (`LLM_ROUTING_DECISION`, `LLM_ROUTING_FALLBACK`) | Kafka topic definitions |
| `src/omniclaude/nodes/node_agent_routing_compute/handler_routing_llm.py` | LLM routing handler (ONEX node) |

---

## Anti-Patterns

Do not use `model_copy()` to change URL fields on a `LocalLlmEndpointRegistry` instance. The `_endpoint_configs` cache is a `cached_property` stored in `__dict__`, which is shared between the original and the copy. Always construct a new instance when URL fields need to change.

Do not hardcode endpoint URLs in calling code. Always use `LocalLlmEndpointRegistry().get_endpoint(purpose)`. This ensures the correct model is used even when the deployment topology changes.
