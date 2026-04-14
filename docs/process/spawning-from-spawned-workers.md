# Spawning Sub-Workers from Orchestrator Workers (OMN-8708)

## The Problem

When an orchestrator (e.g. `epic-team`, `session`, `pipeline-fill`) dispatches a worker via
`Agent(team_name=...)`, the worker runs in a fresh Claude Code session. In fresh sessions,
the `Agent` tool (along with `SendMessage`, `TaskCreate`, `TaskUpdate`, `TaskGet`) is
**deferred** — the schema is not pre-loaded.

A deferred tool appears by name in `<available-deferred-tools>` but cannot be called until
its schema is fetched with `ToolSearch`. Without the fetch, any call to `Agent(...)` inside
the worker produces:

```text
Error: Agent tool unavailable — schema not loaded
```

This blocks recursive dispatch: any orchestrator skill that is itself invoked _as_ a worker
cannot spawn further sub-workers without explicitly fetching the schema first.

## Affected Skills

All orchestrator skills that spawn workers are affected:

| Skill | Spawns workers? | Worker needs Agent? |
|-------|----------------|---------------------|
| `epic-team` | Yes (ticket-pipeline per ticket) | Yes (verifier sub-agents) |
| `session` | Yes (Phase 3 dispatch) | Yes (merge-sweep, epic-team workers) |
| `pipeline-fill` | Yes (ticket-pipeline workers) | Yes |
| `ticket-pipeline` | Conditionally | Yes (verifier agents) |
| `merge-sweep` | Yes (pr-polish Track B) | Yes |
| `build-loop` | Yes (closeout workers) | Yes |
| `overnight` | Yes (merge-sweep + build-loop workers) | Yes |
| `autopilot` | Yes (phase sub-workers) | Yes |

## The Fix (Zero-Effort Workaround)

Every `Agent()` dispatch prompt must include the following as its **first instruction**:

```text
ToolSearch(query="select:Agent,SendMessage,TaskCreate,TaskUpdate,TaskGet", max_results=5)
```

This fetches the full schemas for all five dispatch tools in a single call before the worker
does anything else. After this call completes, all five tools are fully callable for the
remainder of the worker session.

## Where It's Documented

Each affected orchestrator skill's `SKILL.md` now contains a **"Tools Required (OMN-8708)"**
section at the top of its body that explains this requirement and shows the exact call to
include in dispatch prompts.

## Why Not Fix It in the Platform?

As of 2026-04-13, there is no `deferred_tools` knob in `settings.json` or the plugin
manifest to universally pre-load schemas. The `Agent` tool is always deferred in fresh
sessions. Changing this would require a Claude Code platform change outside our control.

The skill-level documentation fix is the correct approach: it makes the requirement explicit
and co-located with the dispatch logic, so future skill authors encounter it when writing
new orchestrators.

## For New Skill Authors

If you are writing a new skill that:
1. Spawns workers via `Agent()`
2. Those workers may themselves need to dispatch agents

Then:
1. Add a **"Tools Required"** section to your `SKILL.md` (copy from `epic-team/SKILL.md`)
2. Include the `ToolSearch` call as the first line of every dispatch prompt
3. Add your skill to the table above

## Verification

A worker session that correctly fetches the schema will log:

```text
ToolSearch → found: Agent, SendMessage, TaskCreate, TaskUpdate, TaskGet
```

A session that omits the fetch and tries to call `Agent()` will error with schema-not-found.
Check `.onex_state/friction/` for logged instances of this failure pattern.
