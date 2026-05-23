---
version: 2.0.0
description: "Dispatch-only shim for local LLM delegation. Classifies prompt, constructs typed input, dispatches to node_delegate_skill_orchestrator (omnimarket) via onex node. No inline LLM calls, no Kafka, no bus bootstrap."
mode: full
level: advanced
debug: false
category: delegation
tags: [delegation, dispatch-only, thin-shim, local-llm]
composable: false
args:
  - name: prompt
    description: "The task to delegate (e.g., 'write unit tests for verify_registration.py')"
    required: true
  - name: --task-type
    description: "Override task classification: test, document, research, code_generation, refactor, reasoning, review (default: auto-classify from prompt)"
    required: false
  - name: --max-tokens
    description: "Maximum tokens for the LLM response (default: 2048)"
    required: false
inputs:
  - name: prompt
    description: "User prompt to delegate to a local LLM"
outputs:
  - name: status
    description: "completed | failed | timeout"
  - name: response
    description: "LLM response content"
  - name: model_name
    description: "Model that handled the request"
  - name: cost_savings_usd
    description: "Estimated cost savings vs Claude baseline"
---

# /onex:delegate — dispatch-only shim

**Skill ID**: `onex:delegate` · **Backing node**: `omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/` · **Ticket**: OMN-10604

## Task Types

| Task Type | When to use | Routed model |
|-----------|------------|--------------|
| `test` | write tests, pytest, assertions | Qwen3-Coder or DeepSeek-R1 |
| `document` | docstrings, README, explanations | DeepSeek-R1 |
| `research` | investigate, analyze, explain | DeepSeek-R1 |
| `code_generation` | write code, create app, implement | Qwen3-Coder |
| `refactor` | refactoring, cleanup | Qwen3-Coder |
| `reasoning` | think through, analyze decision | DeepSeek-R1 |
| `review` | code review, audit | DeepSeek-R1 |

## Usage

```
/delegate explain what a calendar app needs
/delegate --task-type code_generation write a Python HTTP server
/delegate --max-tokens 4096 analyze the routing architecture
/delegate --task-type test write unit tests for verify_registration.py
```

## What This Skill Does NOT Do

- Publish through the legacy hook emission client
- Require the Claude hook emit daemon
- Open transport clients from the omniclaude skill surface
- Run skill-local terminal-result waits or inference
- Call any LLM directly
- Run quality gates

## Related

- **TaskClassifier**: `src/omniclaude/lib/task_classifier.py`
- **Market adapter**: `omnimarket.adapters.claude_code.delegate.DelegationDispatchAdapter`
- **Orchestrator contract**: `omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/contract.yaml`
