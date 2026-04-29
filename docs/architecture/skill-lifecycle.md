# Skill Lifecycle: When a Skill Stays in omniclaude vs. Moves to omnimarket

**Status**: Current
**Last verified**: 2026-04-29
**Owner**: omniclaude (this repo)

**Context plans** (in `omni_home/docs/plans/`):
- `2026-04-06-omniclaude-extraction-to-omnimarket.md` — extraction implementation plan
- `2026-04-09-omnimarket-skill-decomposition-design.md` — target domain package structure

---

## The One Rule

> A skill file (`SKILL.md`) is a **thin UX trigger**. It publishes a command
> event and formats a result. It contains no multi-step orchestration logic.

If your skill has more than one `## Step` section that describes execution
logic, it is an orchestrator that belongs in omnimarket, not a skill stub in
omniclaude.

---

## Boundary Table

| Belongs in omniclaude | Belongs in omnimarket |
|----------------------|----------------------|
| `/skill-name` invocation surface | Multi-step workflow FSM |
| Prompt formatting and UX text | State persistence across steps |
| Routing the invocation to the correct Market node | Retry logic and circuit breakers |
| Static configuration (which node to call) | Error classification and recovery |
| Agent YAML definitions | Business rule evaluation |
| Hook scripts (session lifecycle) | Long-running background processes |
| Context injection (pattern enrichment) | Kafka consumer loops |
| Event emission (fire-and-forget to daemon) | Cross-repo coordination logic |

---

## Decision Flowchart

```
New automation needed
        |
Does it need to run outside Claude Code?
  (headless, cron, Cursor, Codex, other IDE)
        |
       YES ──────────────────────────────────► omnimarket node
        |
       NO
        |
Does it run for more than a few seconds synchronously?
        |
       YES ──────────────────────────────────► omnimarket node
        |
       NO
        |
Does it store state between invocations?
        |
       YES ──────────────────────────────────► omnimarket node
        |
       NO
        |
Does it have more than one execution step?
        |
       YES ──────────────────────────────────► omnimarket node + thin skill stub here
        |
       NO
        |
       ──────────────────────────────────────► skill stub in omniclaude only
```

---

## Concrete Examples

### Stays in omniclaude only

**`/login`** — binds the terminal to a named agent. One action, no state, no
external execution.

**`/recall`** — queries the memory index, formats results. Pure lookup, no
orchestration.

**`/set_session`** — writes a session marker file. Single side effect, no
multi-step logic.

### Thin stub in omniclaude, execution in omnimarket

**`/merge_sweep`** — the skill stub dispatches to `node_pr_lifecycle_orchestrator`
in omnimarket. The multi-step poll-triage-merge logic lives in the node.

**`/dod_sweep`** — the skill stub dispatches to `node_dod_sweep_orchestrator`.
The verification contract and evidence checks run in the node.

**`/ticket_pipeline`** — the skill stub dispatches to the pipeline domain package
in omnimarket. Phase sequencing, state machine, and CI watch loop are all in
the node.

### Not a skill at all

**Emit daemon** — started by `session-start.sh`, not a skill. Runs persistently.
Implementation lives entirely in omnimarket `node_emit_daemon`.

**Intelligence processing** — runs in omniintelligence. omniclaude emits the
event; omniintelligence processes it. No skill involved.

---

## What "Thin Stub" Looks Like

A correct skill stub in omniclaude has this shape:

```markdown
# merge_sweep

## Overview

Polls open PRs, enables auto-merge on ready PRs, and nudges stuck queues.
Dispatches to the `pr_lifecycle` domain package in omnimarket.

## Quick Start

/merge_sweep

## Methodology

1. Dispatch command event to omnimarket `node_pr_lifecycle_orchestrator`
2. Display results when the orchestrator completes

## Notes

- Logic lives in omnimarket. Do not add execution steps here.
- See omnimarket for internals.
```

The stub does not describe the merge algorithm, retry policy, or triage logic.
Those descriptions belong in omnimarket's node documentation.

---

## Migration: Moving a Skill to omnimarket

When a skill that currently contains logic needs to move:

1. Create the omnimarket node in a worktree under `$OMNI_HOME/omni_worktrees/<ticket>/omnimarket/`
2. Move the execution logic into the node handler
3. Add a contract YAML to the node declaring its topics
4. Replace the skill body in omniclaude with a thin dispatch stub
5. Update `docs/INDEX.md` in this repo to link to the omnimarket node docs
6. Ship both PRs in the same Linear ticket

Reference: the April 2026 extraction plan and the skill decomposition design
(both in `omni_home/docs/plans/`) describe the full target domain structure
(11 domains, ~80-120 nodes).

---

## Migration Status (as of 2026-04-29)

The extraction is ongoing under the OMN-8002 epic. Current state:

- ~133 node directories in `src/omniclaude/nodes/` are queued for migration to omnimarket
- Skill shims (`node_skill_*`) are allowed as temporary wrappers — no custom handler code
- The emit daemon extraction is complete (OMN-7628)
- `TopicBase` enum extraction is complete (OMN-9335)

Do not add new handler logic to existing `src/omniclaude/nodes/` directories.
All new node handlers go directly to omnimarket.

---

## See Also

- [omnimarket](https://github.com/OmniNode-ai/omnimarket) — canonical home for workflow packages
- [Adding a Skill](../guides/ADDING_A_SKILL.md) — step-by-step skill creation guide
- [omniclaude charter](charter.md) — full ownership boundary declaration
