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

Three packages, one environment (see `plugin-compat.yaml` → `onex_cli`, the pin's
source of truth):

| Package | Provides |
|---|---|
| `omnibase-core >= 0.46.8` | the `onex` console script and the `onex.cli` entry-point loader |
| `omnibase-infra >= 0.38.4` | the `delegate` subcommand, registered into the `onex.cli` group |
| `omnimarket` | `node_delegate_skill_orchestrator`, the node the subcommand dispatches |

**`omnimarket` MUST be installed from git, not a PyPI version pin.** `onex
delegate` runs a pre-flight drift guard
(`omnibase_infra.cli.omnimarket_drift_guard`) before every REAL
dispatch — `--help` below is answered before the guard ever runs. On a
machine that has a canonical `omnimarket` clone checked out under the
workspace root the guard reads (true for every OmniNode dev workspace, not
for a customer) the guard REJECTS an `omnimarket` install that is not a
git-VCS install matching that clone's checked-out commit exactly.
`omnimarket>=0.4.7` (PyPI) carries no VCS provenance and fails this check by
construction, every time — not intermittently (live-reproduced).

Install (this is the command to run):

```bash
uv tool install --with 'omnibase-infra>=0.38.4' --with 'omnimarket @ git+https://github.com/OmniNode-ai/omnimarket.git@dev' 'omnibase-core>=0.46.8'
# or:
pipx install 'omnibase-core>=0.46.8' && pipx inject omnibase-core 'omnibase-infra>=0.38.4' 'omnimarket @ git+https://github.com/OmniNode-ai/omnimarket.git@dev'
```

It names no directory, so there is nothing for it to resolve wrongly. It
installs the `dev` branch tip, and it says so. It used to expand a
workspace variable with a `.` fallback and run `git -C
<that>/omnimarket rev-parse HEAD 2>/dev/null || echo dev`: on a machine where
that variable was unset — every customer machine — the expansion became the
**current working directory**, `rev-parse` failed there, and the `|| echo
dev` swallowed the failure. You got an unpinned `dev` install from a command
that read like a commit pin, with no error either way.

Nothing is lost by pinning `dev` outright. A machine with no canonical clone
never reaches the drift guard at all: it fails OPEN when it cannot determine
a canonical commit to compare against, which is exactly the machine this
command is for.

**On an OmniNode workspace machine** the guard *does* bite, so pin to your
own clone's commit instead. Export `OMNIBASE_PATH` to your workspace root
first; the `:?` refuses loudly rather than falling back to the wrong
directory if you have not:

```bash
OMNIMARKET_REF="$(git -C "${OMNIBASE_PATH:?export OMNIBASE_PATH to your OmniNode workspace root}/omnimarket" rev-parse HEAD)" \
  && uv tool install --with 'omnibase-infra>=0.38.4' \
       --with "omnimarket @ git+https://github.com/OmniNode-ai/omnimarket.git@${OMNIMARKET_REF}" \
       'omnibase-core>=0.46.8'
```

That ref is an exact match against the guard's own comparison basis, by
construction. Note the guard itself still reads the older `OMNI_HOME`
spelling of the same workspace root; export both to the same path until that
rename reaches it.

Verify: `onex delegate --help` must exit 0 **from any directory**.

`--help` alone is not proof the command works — click answers it before any
dispatch. If `omnimarket` is missing entirely, `--help` still exits 0 and the
first real invocation fails with `Error: Unknown node
'node_delegate_skill_orchestrator'`, listing ~130 unrelated nodes as "known".
If `omnimarket` is present but PyPI-installed (or stale) on a machine the
drift guard covers, the first real invocation instead fails with
`OmnimarketDriftError`. The node is found through the `onex.nodes`
entry-point group over **installed distributions**, so once installed this
way no workspace-root access of any kind is needed to dispatch.

Proven end-to-end: a scratch venv built from exactly this recipe passes
`omnimarket_drift_guard.check_omnimarket_drift()` with zero drift and
resolves `node_delegate_skill_orchestrator` from the installed
distribution, not a workspace checkout
(`plugins/onex-delegate/tests/test_install_works.py`).

**Do not run `uv run onex delegate`.** `uv run` resolves the venv of whatever
project the *current directory* belongs to, so the command only works inside a
repo that happens to co-install `omnibase-infra`, and fails everywhere else with
`Error: No such command 'delegate'`. Install the CLI as a tool (above) and call
the bare `onex` on PATH.

Installing `omnibase-core` alone is not enough — `onex` will load, but
`onex delegate` exits 2 with `Error: No such command 'delegate'. Did you mean
'gate'?`.

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
