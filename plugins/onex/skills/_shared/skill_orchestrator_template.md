---
description: Canonical SKILL.md template for orchestrator-shim skills backed by an omnimarket node.
mode: orchestrator-shim
version: 1.0.0
args:
  - name: example_arg
    type: str
    required: false
    description: Pass-through to the backing node command.
inputs:
  - source: foreground prompt
    description: User-typed slash-command invocation.
outputs:
  - target: foreground caller
    description: Typed result returned by the backing node, plus optional Agent() spawn.
---

# Canonical Skill Orchestrator-Shim Template

This file is a template, not an executable skill. Every migrated SKILL.md adopts
this shape. Replace `<node>`, `<archetype>`, `<allowed-args>`, etc. when authoring.
The shape is enforced by `tests/unit/test_skill_orchestrator_shape.py`.

## What this skill does

One paragraph. Name the backing omnimarket node module (for example
`omnimarket.nodes.node_<name>`) and the archetype (`dispatch_worker`,
`deterministic_node`, or `review_worker`). State the foreground-visible behavior
without describing handler internals.

## Dispatch

The skill invokes its backing node via the standard ONEX runner. Foreground
runs (no executable code fence — this is documentation):

    uv run onex run-node <node> -- <allowed-args>

Foreground waits synchronously for the typed result. The handler MUST NOT call
`Agent()`. See foreground-only Agent() ADR
`adr-dispatch-architecture-foreground-only-agent-call` in `omnimarket/docs/decisions/`.

## Foreground responsibility

1. Parse skill args from the slash-command invocation.
2. Invoke `uv run onex run-node <node>` with the parsed args.
3. Read the typed result returned by the node handler.
4. Act per archetype:
   - `dispatch_worker` — read `proposed_agent_spawn_args`; call `TeamCreate`
     (if no team exists) + `TaskCreate` + `Agent(team_name=..., name=...)`.
     Return the correlation_id.
   - `deterministic_node` — return or persist the typed result directly. No
     `Agent()` spawn.
   - `review_worker` — return or persist the typed result directly. No
     `Agent()` spawn.
5. Exit. The skill never blocks waiting for worker completion.

## Worker self-verification

Every worker spawned by this skill (when the archetype is `dispatch_worker`)
follows the same pre-push checklist before reporting "Primary task done":

- Run `uv run pytest tests/ -v` with no `-k` filter (full suite, no narrow filter)
- Run ruff format + ruff check on `src/` and `tests/`
- Run `pre-commit run --all-files` and address every failure
- Open the PR, then call `gh pr checks <num> --watch` until green
- Send `Primary task done — awaiting further instruction or shutdown.` to the
  reporter via SendMessage; do not mark TaskUpdate completed unless tests are
  green and the PR is open

## Backing node contract

The backing node's full input/output contract lives in
`omnimarket/src/omnimarket/nodes/<node>/contract.yaml`. The handler module is
referenced under `handler:` in that contract. The foreground-only `Agent()`
invariant comes from `adr-dispatch-architecture-foreground-only-agent-call.md`
in `omnimarket/docs/decisions/`.

## Failure modes

- **Kafka unreachable** — `uv run onex run-node` fails with a transport error.
  Surface the error to the foreground caller; do not silently continue.
- **Node rejected the spec** — the typed result includes `rejected_reason`.
  Foreground prints the rejection and exits without spawning a worker.
- **Prompt compile failed** — handler raises during template rendering. The
  CLI exits non-zero; the skill propagates the exit code.
- **Agent spawn unavailable in current context** — the skill is being invoked
  from a subagent or headless context that lacks the `Agent` tool. Detect via
  tool availability and surface a clear error rather than silently dropping
  the dispatch. The broker pattern (Pattern B in the foreground-only Agent()
  ADR) is the long-term fix.
