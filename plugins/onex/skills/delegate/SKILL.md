---
version: 3.0.0
description: "Single-command local LLM delegation. Runs `uv run onex delegate \"<prompt>\"` which builds the payload, dispatches node_delegate_skill_orchestrator, and prints one typed ModelSkillResult[ModelDelegateSkillResponse]. Handled inline — no subagent, no payload file, no cat of workflow_result.json."
skill_kind: dispatch
mode: full
level: advanced
debug: false
category: delegation
tags: [delegation, dispatch, single-command, local-llm]
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

# /onex:delegate — single-command delegation

**Skill ID**: `onex:delegate` · **Command**: `uv run onex delegate` (omnibase_infra) · **Backing node**: `node_delegate_skill_orchestrator` (omnimarket) · **Tickets**: OMN-10604, OMN-13096

A dispatch skill IS one CLI call. The procedure lives in the `onex delegate`
entrypoint — payload construction, node dispatch, and result extraction are all
internal. See `prompt.md` for the one command and how to present the typed result.

## Task Types

| Task Type | When to use |
|-----------|-------------|
| `test` | write tests, pytest, assertions |
| `document` | docstrings, README, explanations |
| `research` | investigate, analyze, explain (default) |
| `code_generation` | write code, create app, implement |
| `refactor` | refactoring, cleanup |
| `reasoning` | think through, analyze a decision |
| `review` | code review, audit |

Omit `--task-type` to auto-classify from the prompt (`onex delegate` applies the
keyword table above; routing is owned by the node contract's `allowed_task_types`).

## Usage

```
/delegate explain what a calendar app needs
/delegate --task-type code_generation write a Python HTTP server
/delegate --max-tokens 4096 analyze the routing architecture
/delegate --task-type test write unit tests for verify_registration.py
```

## What This Skill Does NOT Do

- Construct a payload temp file, `cd` to omnimarket, or `cat` workflow_result.json (all internal to `onex delegate`)
- Spawn a general-purpose subagent (exempted from the delegation enforcer — `skill_kind: dispatch`)
- Call any LLM directly, publish through the legacy hook emission client, or open transport clients from the skill surface

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_delegate.py`
- **Result model**: `omnimarket/src/omnimarket/models/delegation/wire/model_delegate_skill_response.py`
- **Orchestrator contract**: `omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/contract.yaml`
