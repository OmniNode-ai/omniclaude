---
version: 1.0.3
description: Delegate tasks to the ONEX node-based delegation pipeline through local runtime ingress and the Pattern B broker. Classifies prompt, wraps a typed runtime request, and lets the runtime own event-bus dispatch and terminal correlation.
mode: full
level: advanced
debug: true
index: true
args:
  - name: prompt
    description: "The task to delegate (e.g., 'write unit tests for verify_registration.py')"
    required: true
  - name: --source-file
    description: "Source file path for context (optional)"
    required: false
  - name: --max-tokens
    description: "Maximum tokens for the LLM response (default: 2048)"
    required: false
  - name: --recipient
    description: "Target CLI recipient: auto, claude, opencode, or codex"
    required: false
  - name: --wait
    description: "Request runtime terminal-result correlation instead of fire-and-forget routing"
    required: false
---

# Delegate

Thin skill that classifies a user prompt and submits a typed runtime request to
`node_delegation_orchestrator`. The skill does not publish directly to Kafka and
does not depend on the Claude hook emit daemon. Runtime ingress and the Pattern B
broker own route resolution, event-bus dispatch, terminal-result correlation,
serialization, and transport errors.

## How It Works

1. Parse the user's prompt.
2. Classify the task type using `TaskClassifier`.
3. Construct a `ModelDelegationCommand`-compatible payload.
4. Submit `ModelRuntimeSkillRequest(command_name="node_delegation_orchestrator")`
   through `LocalRuntimeSkillClient`.
5. Return the runtime response with the correlation ID, broker dispatch status,
   resolved node, command topic, and terminal event when available.

## Task Types

Classification maps to three delegatable intents from `TaskClassifier`:

| Task Type | Trigger Keywords | Example |
|-----------|-----------------|---------|
| `test` | test, testing, unit test, pytest, assert | "write unit tests for verify_registration.py" |
| `document` | document, docstring, README, explain | "add docstrings to the handler module" |
| `research` | what, how, explain, investigate, analyze | "what does the routing reducer do?" |

Non-delegatable intents are rejected before runtime dispatch.

## Runtime Request Payload

```json
{
  "prompt": "write unit tests for verify_registration.py",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "session-abc123",
  "prompt_length": 43,
  "source_file_path": "/path/to/verify_registration.py",
  "max_tokens": 2048,
  "recipient": "auto",
  "wait_for_result": false,
  "working_directory": null,
  "codex_sandbox_mode": null
}
```

The payload remains compatible with `ModelDelegationCommand`; runtime-side
validation occurs on the consuming `node_delegation_orchestrator`.

## Runtime Path

- **Skill client**: `LocalRuntimeSkillClient`
- **Request model**: `ModelRuntimeSkillRequest`
- **Command name**: `node_delegation_orchestrator`
- **Runtime ingress**: `ONEX_LOCAL_RUNTIME_SOCKET_PATH` or `/tmp/onex-runtime.sock`
- **Broker route**: Pattern B broker resolves the command topic from the node contract
- **Legacy topic**: `onex.cmd.omniclaude.delegate-task.v1` is runtime-owned, not skill-owned

## Usage

```
/delegate write unit tests for verify_registration.py
/delegate --source-file src/omniclaude/hooks/handler_event_emitter.py add docstrings
/delegate --max-tokens 4096 --recipient codex analyze the routing architecture
/delegate --wait research the cross-CLI bridge terminal-result flow
```

## What This Skill Does NOT Do

- Publish through the legacy hook emission client
- Require the Claude hook emit daemon
- Open a Kafka producer or consumer
- Run skill-local terminal-result waits
- Call any LLM directly
- Run quality gates

## Related

- **Bridge implementation**: `plugins/onex/skills/delegate/_lib/run.py`
- **TaskClassifier**: `src/omniclaude/lib/task_classifier.py`
- **Runtime client**: `omnibase_infra.clients.runtime_skill_client.LocalRuntimeSkillClient`
- **Request model**: `omnibase_core.models.runtime.ModelRuntimeSkillRequest`
- **Orchestrator contract**: `src/omniclaude/nodes/node_delegation_orchestrator/contract.yaml`
