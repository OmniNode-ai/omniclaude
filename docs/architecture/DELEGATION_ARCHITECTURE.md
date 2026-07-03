# Delegation Architecture

**Last Updated**: 2026-06-20
**Key changes**: delegation flags removed (unconditional bridge), bridge wired, topic alignment, bridge handler removed, dead bridge invocation removed from `user-prompt-submit.sh`

> **STATUS — bridge removed:** The `UserPromptSubmit` hook no longer
> auto-fires a delegation bridge. The `handler_delegate_skill.py` adapter this doc
> describes was deleted in an earlier cleanup, and its sole remaining caller (a dead block in
> `user-prompt-submit.sh` that always logged a "handler not found" warning) was removed
> in a subsequent cleanup. Delegation now runs only on explicit invocation of the `/onex:delegate`
> skill, which dispatches `node_delegate_skill_orchestrator` (omnimarket). The
> Kafka-bridge flow below is retained for historical context only and is **not wired**.

---

## Overview (historical — bridge no longer wired)

The delegation system routed user prompts to the ONEX node pipeline via Kafka. Every
non-slash, non-automated prompt that entered `UserPromptSubmit` was classified and
published to `onex.cmd.omniclaude.delegate-task.v1`. The runtime
`node_delegation_orchestrator` handled routing, LLM inference, quality gating, and
result emission.

**There was no local prose fallback.** Delegation required Kafka to be reachable.
If the emit daemon was unavailable, the request was dropped and Claude handled the
prompt normally.

---

## Architecture Diagram

```
UserPromptSubmit
    │
    ▼ (non-slash, non-automated prompts only)
plugins/onex/skills/delegate/_lib/handler_delegate_skill.py
    │
    ├─ TaskClassifier.classify(prompt) → TaskContext
    │    delegatable intents: test, document, research, implement
    │    non-delegatable → no publish, returns success=False
    │
    ├─ Construct ModelEventEnvelope-compatible dict
    │    { payload: { prompt, task_type, correlation_id, ... },
    │      correlation_id, event_type, source_tool }
    │
    └─ EmitClient.emit_event("delegate.task", envelope)
         → onex.cmd.omniclaude.delegate-task.v1
         → [RUNTIME SIDE] node_delegation_orchestrator
              → node_delegation_routing_reducer
              → node_llm_inference_effect
              → node_delegation_quality_gate_reducer
              → onex.evt.omniclaude.delegation-completed.v1
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
  "event_type": "omniclaude.delegate-task",
  "source_tool": "omniclaude.delegate-skill"
}
```

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/skills/delegate/_lib/handler_delegate_skill.py` | Classify + publish to Kafka |
| `src/omniclaude/lib/task_classifier.py` | Prompt classification |
| `src/omniclaude/hooks/topics.py` (`DELEGATE_TASK`) | Kafka topic definition |

> The `user-prompt-submit.sh` bridge invocation row was subsequently removed: the hook
> no longer calls a delegation bridge (see the status banner at the top of this doc).

---

## Failure Modes (historical — bridge no longer wired)

| Failure | Behavior |
|---------|----------|
| Kafka / emit daemon unavailable | Request dropped; Claude handles prompt |
| Non-delegatable intent | No publish; success=False logged |
| TaskClassifier import error | No publish; error logged |
