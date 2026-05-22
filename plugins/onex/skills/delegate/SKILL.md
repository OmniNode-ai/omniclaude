---
version: 1.1.0
description: Delegate tasks to the ONEX delegation pipeline via the market adapter. Classifies prompt, wraps a typed dispatch payload, and routes through DelegationDispatchAdapter → node_delegate_skill_orchestrator.
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
  - name: --local
    description: "Run in-process using local vLLM endpoint (debug/demo only — no Kafka or runtime required)"
    required: false
---

# Delegate

Thin skill shim that classifies a user prompt and dispatches through the market
delegation adapter. The shim has no transport logic; all route resolution,
event-bus dispatch, topic naming, and terminal-result correlation are owned by
`DelegationDispatchAdapter` in omnimarket.

## How It Works

1. Parse the user's prompt.
2. Classify the task type using `TaskClassifier`.
3. Build a typed dispatch payload.
4. Route through `DelegationDispatchAdapter` → contract-declared runtime dispatch
   → `node_delegate_skill_orchestrator`.
5. Return the correlation ID, dispatch status, resolved node, command topic, and
   terminal event when available.

For `--local`: bypass the adapter entirely and run the delegation pipeline
in-process using a local vLLM endpoint via curl shim (debug/demo path only).

## Dispatch Path

```
omniclaude skill shim
  └─► DelegationDispatchAdapter  (omnimarket)
        └─► contract-declared runtime dispatch
              └─► node_delegate_skill_orchestrator
```

Debug path (--local flag):

```
omniclaude skill shim
  └─► InprocessRunner  (no Kafka, no runtime socket, no projection)
```

## Task Types

Classification maps to three delegatable intents from `TaskClassifier`:

| Task Type | Trigger Keywords | Example |
|-----------|-----------------|---------|
| `test` | test, testing, unit test, pytest, assert | "write unit tests for verify_registration.py" |
| `document` | document, docstring, README, explain | "add docstrings to the handler module" |
| `research` | what, how, explain, investigate, analyze | "what does the routing reducer do?" |

Non-delegatable intents are rejected before adapter dispatch.

## Dispatch Payload

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

The payload is forwarded to `node_delegate_skill_orchestrator` via the adapter;
runtime-side validation occurs there.

## Usage

```
/delegate write unit tests for verify_registration.py
/delegate --source-file src/omniclaude/hooks/handler_event_emitter.py add docstrings
/delegate --max-tokens 4096 --recipient codex analyze the routing architecture
/delegate --wait research the cross-CLI bridge terminal-result flow
/delegate --local write a failing test for the classifier
```

## What This Skill Does NOT Do

- Open a Kafka producer or consumer directly
- Publish via HTTP, SSH socket, Pandaproxy, or SSH rpk bridge
- Require the Claude hook emit daemon
- Call any LLM directly
- Run quality gates

## Related

- **Bridge implementation**: `plugins/onex/skills/delegate/_lib/run.py`
- **TaskClassifier**: `src/omniclaude/lib/task_classifier.py`
- **Market adapter**: `omnimarket.adapters.claude_code.delegate.DelegationDispatchAdapter`
- **Orchestrator contract**: `omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/contract.yaml`
