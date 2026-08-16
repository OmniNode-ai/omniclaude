---
version: 3.0.0
description: "Single-command local LLM delegation. Runs `onex delegate \"<prompt>\"` which builds the payload, dispatches node_delegate_skill_orchestrator, and prints one typed ModelSkillResult[ModelDelegateSkillResponse]. Handled inline — no subagent, no payload file, no cat of workflow_result.json."
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

**Skill ID**: `onex:delegate` · **Command**: `onex delegate` · **Backing node**: `node_delegate_skill_orchestrator` (omnimarket)

A dispatch skill IS one CLI call. The procedure lives in the `onex delegate`
entrypoint — payload construction, node dispatch, and result extraction are all
internal. See `prompt.md` for the one command and how to present the typed result.

## Prerequisite: install the `onex` CLI *with* the delegate subcommand

Two packages, one environment (see `plugin-compat.yaml` → `onex_cli`, the pin's
source of truth):

| Package | Provides |
|---|---|
| `omnibase-core >= 0.46.8` | the `onex` console script and the `onex.cli` entry-point loader |
| `omnibase-infra >= 0.38.4` | the `delegate` subcommand, registered into the `onex.cli` group |

```bash
uv tool install --with 'omnibase-infra>=0.38.4' 'omnibase-core>=0.46.8'
# or:
pipx install 'omnibase-core>=0.46.8' && pipx inject omnibase-core 'omnibase-infra>=0.38.4'
```

Verify: `onex delegate --help` must exit 0 **from any directory**.

**Do not run `uv run onex delegate`.** `uv run` resolves the venv of whatever
project the *current directory* belongs to, so the command only works inside a
repo that happens to co-install `omnibase-infra`, and fails everywhere else with
`Error: No such command 'delegate'`. Install the CLI as a tool (above) and call
the bare `onex` on PATH.

Installing `omnibase-core` alone is not enough — `onex` will load, but
`onex delegate` exits 2 with `Error: No such command 'delegate'. Did you mean
'gate'?`.

> **Known gap (OMN-16041):** the pins above are not yet satisfiable from PyPI.
> The newest published `omnibase-infra` is 0.36.1, whose `omnibase-spi>=0.21,<0.22`
> pin cannot resolve against the published `omnibase-spi` 0.23.1, and an unpinned
> install silently backtracks to 0.32.0, which predates the `delegate` entry point.
> `omnibase_infra@main` is already at 0.38.4 with correct pins; the outstanding
> step is cutting the `v0.38.4` PyPI release. Until then, install from a built
> `omnibase_infra` wheel:
> `uv tool install --with ./omnibase_infra-0.38.4-py3-none-any.whl 'omnibase-core==0.46.8'`.

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
/onex:delegate explain what a calendar app needs
/onex:delegate --task-type code_generation write a Python HTTP server
/onex:delegate --max-tokens 4096 analyze the routing architecture
/onex:delegate --task-type test write unit tests for verify_registration.py
```

## What This Skill Does NOT Do

- Construct a payload temp file, `cd` to omnimarket, or `cat` workflow_result.json (all internal to `onex delegate`)
- Spawn a general-purpose subagent (exempted from the delegation enforcer — `skill_kind: dispatch`)
- Call any LLM directly, publish through the legacy hook emission client, or open transport clients from the skill surface

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_delegate.py`, registered as `[project.entry-points."onex.cli"] delegate` in `omnibase_infra/pyproject.toml`
- **Console script**: `omnibase_core/pyproject.toml` `[project.scripts] onex`; the `onex.cli` group loader is `omnibase_core/src/omnibase_core/cli/cli_commands.py`
- **Pin source of truth**: `plugins/onex-delegate/plugin-compat.yaml` → `onex_cli`
- **Result model**: `omnimarket/src/omnimarket/models/delegation/wire/model_delegate_skill_response.py`
- **Orchestrator contract**: `omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/contract.yaml`
