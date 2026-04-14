# Delegation Architecture

**Last Updated**: 2026-04-14
**Tickets**: OMN-8746 (remove delegation flags, unconditional bridge), OMN-8689 (bridge)

---

## Overview

The delegation system routes user prompts to the ONEX node pipeline via Kafka. Every
non-slash, non-automated prompt that enters `UserPromptSubmit` is classified and
published to `onex.cmd.omnibase-infra.delegation-request.v1`. The runtime
`node_delegation_orchestrator` on .201 handles routing, LLM inference, quality
gating, and result emission.

**There is no local prose fallback.** Delegation requires Kafka to be reachable.
If the emit daemon is unavailable, the request is dropped and Claude handles the
prompt normally.

---

## Architecture Diagram

```
UserPromptSubmit
    │
    ▼ (non-slash, non-automated prompts only)
plugins/onex/skills/delegate/_lib/run.py
    │
    ├─ TaskClassifier.classify(prompt) → TaskContext
    │    delegatable intents: test, document, research, implement
    │    non-delegatable → no publish, returns success=False
    │
    ├─ Construct ModelEventEnvelope-compatible dict
    │    { payload: { prompt, task_type, correlation_id, ... },
    │      correlation_id, event_type, source_tool }
    │
    └─ EmitClient.emit_event("delegation.request", envelope)
         → onex.cmd.omnibase-infra.delegation-request.v1
         → [RUNTIME SIDE] node_delegation_orchestrator
              → node_delegation_routing_reducer
              → node_llm_inference_effect
              → node_delegation_quality_gate_reducer
              → onex.evt.omnibase-infra.delegation-completed.v1
```

---

## Wire Schema

```json
{
  "payload": {
    "prompt": "write unit tests for verify_registration.py",
    "task_type": "test",
    "source_session_id": "session-abc123",
    "source_file_path": "/path/to/verify_registration.py",
    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
    "max_tokens": 2048,
    "emitted_at": "2026-04-14T14:30:00Z"
  },
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "omnibase-infra.delegation-request",
  "source_tool": "omniclaude.delegate-skill"
}
```

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/skills/delegate/_lib/run.py` | Classify + publish to Kafka |
| `src/omniclaude/lib/task_classifier.py` | Prompt classification |
| `src/omniclaude/hooks/topics.py` (`DELEGATION_REQUEST`) | Kafka topic definition |
| `plugins/onex/hooks/scripts/user-prompt-submit.sh` | Bridge invocation (fire-and-forget) |

---

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Kafka / emit daemon unavailable | Request dropped; Claude handles prompt |
| Non-delegatable intent | No publish; success=False logged |
| TaskClassifier import error | No publish; error logged |
| Bridge script missing | Warning logged; Claude handles prompt |
