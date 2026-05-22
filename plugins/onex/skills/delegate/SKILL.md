---
version: 1.0.3
description: Delegate tasks through the market-owned delegate skill adapter. Classifies prompt, maps legacy CLI flags to adapter metadata, and lets omnimarket own runtime dispatch and terminal correlation.
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

Thin compatibility skill that classifies a user prompt and submits it through
`omnimarket.adapters.claude_code.delegate.DelegationDispatchAdapter` to
`delegate_skill.orchestrate` on `node_delegate_skill_orchestrator`. The skill
surface does not publish directly to the event bus, does not open transport
clients, and does not run local inference. Omnimarket owns route resolution,
runtime dispatch, terminal-result correlation, serialization, and transport
errors.

## How It Works

1. Parse the user's prompt.
2. Classify the task type using `TaskClassifier`.
3. Map legacy `/onex:delegate` flags into the market adapter payload and metadata.
4. Call `DelegationDispatchAdapter.dispatch_sync(command_name="delegate_skill.orchestrate")`
   for `node_delegate_skill_orchestrator`.
5. Return the adapter response with the correlation ID, resolved node, command
   topic, and terminal event when available.

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
  "metadata": {
    "source_file_path": "/path/to/verify_registration.py",
    "session_id": "session-abc123",
    "recipient": "auto",
    "working_directory": null,
    "codex_sandbox_mode": null
  },
  "max_tokens": 2048,
  "wait": false
}
```

The payload is compiled by the market adapter; runtime-side validation occurs on
the consuming `node_delegate_skill_orchestrator`.

## Runtime Path

- **Skill adapter**: `omnimarket.adapters.claude_code.delegate.DelegationDispatchAdapter`
- **Command name**: `delegate_skill.orchestrate`
- **Runtime node**: `node_delegate_skill_orchestrator`
- **Command topic**: resolved from the omnimarket delegate skill contract
- **Terminal topics**: resolved from the omnimarket delegate skill contract

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
- Open transport clients from the omniclaude skill surface
- Run skill-local terminal-result waits or inference
- Call any LLM directly
- Run quality gates

## Related

- **Bridge implementation**: `plugins/onex/skills/delegate/_lib/run.py`
- **TaskClassifier**: `src/omniclaude/lib/task_classifier.py`
- **Market adapter**: `omnimarket.adapters.claude_code.delegate.DelegationDispatchAdapter`
- **Orchestrator contract**: `omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/contract.yaml`
