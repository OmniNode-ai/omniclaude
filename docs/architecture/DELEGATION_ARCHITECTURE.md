# Delegation Architecture

**Last Updated**: 2026-02-19
**Tickets**: OMN-2271 (delegation dispatch), OMN-2281 (delegation orchestrator with quality gate), OMN-2282 (delegation test review)

---

## Overview

The local delegation system routes specific categories of user prompts to a local LLM endpoint instead of Claude. When a prompt is classified as a documentation generation, test generation, or research/code-review task with high confidence, the delegation path calls a local OpenAI-compatible endpoint, applies a quality gate to the response, and returns the result directly to the user. Claude Code never sends the prompt to Anthropic's API for these requests — saving cost and reducing latency for well-defined tasks.

Delegation is conservative by design: it falls back to Claude on any uncertainty. Four gates must all pass before a response is returned. The quality gate is a final heuristic check after the LLM call.

---

## Architecture Diagram

```
UserPromptSubmit
    │
    ├─ [if ENABLE_LOCAL_DELEGATION=true
    │       AND ENABLE_LOCAL_INFERENCE_PIPELINE=true]
    │
    ▼
delegation_orchestrator.orchestrate_delegation(prompt, session_id, correlation_id)
    │
    ├─ Gate 1: Feature flags active?
    │    ENABLE_LOCAL_INFERENCE_PIPELINE AND ENABLE_LOCAL_DELEGATION
    │    No → delegated=False, reason="feature_disabled"
    │
    ├─ Gate 2: Task classification
    │    TaskClassifier.is_delegatable(prompt) → DelegationScore
    │    │
    │    ├─ score.delegatable=False? → delegated=False, reason=reasons
    │    │    (criteria: confidence > 0.9, allowed task type,
    │    │               no vision signals, no tool call signals)
    │    │
    │    └─ score.delegatable=True → continue
    │         TaskClassifier.classify(prompt) → TaskContext
    │         intent_value = ctx.primary_intent.value
    │         ("document", "test", or "research")
    │
    ├─ Gate 3: Endpoint selection
    │    _select_handler_endpoint(intent_value)
    │    → LocalLlmEndpointRegistry.get_endpoint(LlmEndpointPurpose)
    │
    │    Intent → LlmEndpointPurpose mapping:
    │    ┌──────────────┬────────────────────┬─────────────────────┐
    │    │ document     │ REASONING          │ Qwen2.5-72B, R1     │
    │    │ test         │ CODE_ANALYSIS      │ Qwen3-Coder-30B-A3B │
    │    │ research     │ CODE_ANALYSIS      │ Qwen3-Coder-30B-A3B │
    │    └──────────────┴────────────────────┴─────────────────────┘
    │
    │    No endpoint configured? → delegated=False, reason="pre_gate:no_endpoint_configured"
    │
    ├─ Gate 4: Secret redaction
    │    _redact_secrets(prompt) → redacted_prompt
    │    Redaction failure → delegated=False, reason="redaction_error"
    │    (Never forward potentially-sensitive prompts to local LLM)
    │
    ├─ LLM call
    │    _call_llm_with_system_prompt(redacted_prompt, endpoint_url, system_prompt, model_name)
    │    POST /v1/chat/completions  (OpenAI-compatible)
    │    timeout: 7 seconds (_LLM_CALL_TIMEOUT_S)
    │    max_tokens: 2048, temperature: 0.3
    │    Prompt truncated to 8000 chars if needed
    │
    │    Call fails or returns empty? → delegated=False, reason="pre_gate:llm_call_failed"
    │
    ├─ Gate 5: Quality gate (heuristic, < 5ms)
    │    _run_quality_gate(response, task_type)
    │    │
    │    ├─ Check 1: Minimum length
    │    │    document: 100 chars, test: 80 chars, research: 60 chars
    │    │
    │    ├─ Check 2: No refusal indicators in first 200 chars
    │    │    ("i cannot", "i'm unable", "i apologize", "as an ai",
    │    │     "i don't have", "i can't")
    │    │
    │    └─ Check 3: Task-specific content markers (document and test only)
    │         test: ("def test_", "class test", "@pytest", "assert")
    │         document: ('"""', "args:", "returns:", "parameters:")
    │
    │    Gate fails? → delegated=False, reason="quality_gate_failed"
    │
    ├─ [fire-and-forget] _emit_compliance_advisory(response, task_type, ...)
    │    → compliance.evaluate event for the advisory pipeline
    │
    ├─ [fire-and-forget] _emit_delegation_event(delegation_success=True, ...)
    │    → onex.evt.omniclaude.task-delegated.v1
    │
    └─ Return:
       delegated=True:  {"delegated": True, "response": "<formatted>", "model": ...,
                          "confidence": ..., "intent": ..., "savings_usd": ...,
                          "latency_ms": ..., "handler": ..., "quality_gate_passed": True}
       delegated=False: {"delegated": False, "reason": "..."}
```

---

## System Prompts by Task Type

Each intent type receives a specialized system prompt to steer the local model:

| Task Type | System Prompt Focus | Handler Name |
|-----------|--------------------|-|
| `document` | Technical documentation expert, Python docstring format (Args/Returns/Raises) | `doc_gen` |
| `test` | Python testing expert, pytest fixtures, `@pytest.mark.unit` | `test_boilerplate` |
| `research` | Code review and research assistant, identifies issues, suggests improvements | `code_review` |

---

## Quality Gate Details

The quality gate is intentionally a fast heuristic, not a second LLM call. It runs in under 5ms and catches the most common failure modes:

**Minimum length checks**: A response that is too short almost certainly did not complete the task. Thresholds are intentionally conservative (80-100 chars) to avoid false positives on concise but correct responses.

**Refusal indicator scan**: The gate scans only the first 200 characters of the response. Models front-load refusals. This trades thoroughness for speed — a model that buries a refusal after a long preamble will pass this check. That is an acceptable tradeoff for a <5ms gate.

**Task-type content markers**: For `test` tasks, at least one of `def test_`, `class test`, `@pytest`, or `assert` must appear somewhere in the response. For `document` tasks, at least one of `"""`, `args:`, `returns:`, or `parameters:` must appear. `research` tasks have no marker requirement (explanations are more open-ended).

When the quality gate fails, the response is discarded and `delegated=False` is returned. Claude handles the prompt. The failure reason is emitted to `task-delegated.v1` for observability.

---

## Observability

Every call to `orchestrate_delegation()` emits exactly one `task-delegated.v1` event, regardless of outcome. This ensures the success rate metric (golden metric target: >80%) captures all delegation attempts, not just successes.

The `task-delegated.v1` event payload (`ModelTaskDelegatedPayload`):
```json
{
  "session_id": "uuid",
  "correlation_id": "uuid",
  "emitted_at": "2026-02-19T...",
  "task_type": "test",
  "handler_used": "test_boilerplate",
  "model_used": "Qwen3-Coder-30B-A3B-Instruct",
  "quality_gate_passed": true,
  "quality_gate_reason": null,
  "delegation_success": true,
  "estimated_savings_usd": 0.0021,
  "latency_ms": 1240
}
```

The `emitted_at` timestamp is injected by the caller, never set via `datetime.now()` inside the event, following the CLAUDE.md invariant for deterministic testing.

---

## Task Classifier

`TaskClassifier` (in `omniclaude.lib.task_classifier`) determines whether a prompt is delegatable. The `is_delegatable()` method returns a `DelegationScore` with:
- `delegatable: bool` — whether the task should be delegated
- `confidence: float` — classifier confidence (required >0.9 for delegation)
- `reasons: list[str]` — human-readable explanation
- `estimated_savings_usd: float` — estimated cost savings

The `classify()` method returns a `TaskContext` with `primary_intent` (a `TaskIntent` enum with values `document`, `test`, `research`, and others that are not delegatable).

Non-delegatable signals checked by the classifier:
- Vision content in the prompt (image references, screenshots)
- Tool call signals (requests to run code, invoke commands)
- Confidence below 0.9
- Intent types not in the routing table (only `document`, `test`, `research` are delegatable)

The classifier instance is cached as a module-level singleton in `delegation_orchestrator.py` to avoid re-construction on every hook invocation.

---

## Response Formatting

A successful delegation response is formatted with visible attribution:

```
[Local Model Response - Qwen3-Coder-30B-A3B-Instruct]

<model response text>

---
Delegated via local model: confidence=0.923, savings=~$0.0021, handler=test_boilerplate.
Reason: high confidence test generation task; no vision signals; no tool call signals
```

This attribution makes it clear to the user that a local model responded, not Claude. The `savings` field shows the estimated cost savings from not calling the Anthropic API.

---

## Failure Modes

| Gate | Failure Cause | Behavior |
|------|---------------|----------|
| Gate 1 | Feature flags off | `delegated=False, reason="feature_disabled"` |
| Gate 2 | Classification exception | `delegated=False, reason="classification_error:<type>"` |
| Gate 2 | Not delegatable (confidence/type/signals) | `delegated=False, reason=<reasons>` |
| Gate 2 | Intent extraction fails | `delegated=False, reason="pre_gate:intent_extraction_error"` |
| Gate 3 | No endpoint for intent | `delegated=False, reason="pre_gate:no_endpoint_configured"` |
| Gate 4 | Secret redaction fails | `delegated=False, reason="redaction_error"` (safety-first abort) |
| LLM call | `httpx` not installed | `delegated=False, reason="pre_gate:llm_call_failed"` |
| LLM call | HTTP error or timeout | `delegated=False, reason="pre_gate:llm_call_failed"` |
| LLM call | Empty response | `delegated=False, reason="pre_gate:empty_response"` |
| Gate 5 | Response too short | `delegated=False, reason="quality_gate_failed"` |
| Gate 5 | Refusal indicator found | `delegated=False, reason="quality_gate_failed"` |
| Gate 5 | Missing content markers | `delegated=False, reason="quality_gate_failed"` |
| Compliance emit | Any exception | Swallowed silently (fire-and-forget) |
| Delegation event emit | Any exception | Swallowed silently (fire-and-forget) |
| Unexpected exception | Caught at top level | `delegated=False, reason="orchestrator_error"` |

The function `orchestrate_delegation()` NEVER raises. All paths return a dict with at minimum `{"delegated": bool}`.

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/hooks/lib/delegation_orchestrator.py` | Main orchestrator: 5 gates, quality gate, event emission |
| `plugins/onex/hooks/lib/local_delegation_handler.py` | Legacy delegation dispatch (per-prompt subprocess entry point) |
| `src/omniclaude/lib/task_classifier.py` | Prompt classification: is_delegatable, classify |
| `src/omniclaude/config/model_local_llm_config.py` | LLM endpoint registry |
| `src/omniclaude/hooks/schemas.py` (`ModelTaskDelegatedPayload`) | Delegation event schema |
| `src/omniclaude/hooks/topics.py` (`TASK_DELEGATED`, `COMPLIANCE_EVALUATE`) | Kafka topic definitions |

---

## Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `ENABLE_LOCAL_INFERENCE_PIPELINE` | Outer gate for all local inference features | Yes (for delegation) |
| `ENABLE_LOCAL_DELEGATION` | Inner gate for delegation specifically | Yes (for delegation) |
| `LLM_CODER_URL` | Code analysis endpoint (test + research delegation) | Yes (for test/research) |
| `LLM_QWEN_72B_URL` or `LLM_DEEPSEEK_R1_URL` | Reasoning endpoint (document delegation) | Yes (for document) |
| `LOG_FILE` | Log file path for delegation debug output | No |
