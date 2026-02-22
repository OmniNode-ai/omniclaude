# Autonomous Skill Platform — Plan v2

> Created: 2026-02-21
> Updated: 2026-02-22 (F5 consumer group rules added, OMN-2595)
> Status: Active
> Parent epic: OMN-2591

---

## F5 — Consumer Group Rules

**Purpose**: Ensure exactly-once semantics and prevent silent schema drift for all
cmd-topic consumers in the autonomous skill platform.

### Rules

#### F5.1 — No compact cmd topics

**Rule**: No `onex.cmd.*` topic may use `cleanup.policy=compact`.

**Rationale**: cmd topics require full offset replay for exactly-once semantics.
`compact` retention discards intermediate events, breaking replay guarantees.
Only `onex.evt.*` (event/observation) topics may use `compact`.

**Enforcement**: CI check (`arch-no-compact-cmd-topic`) — build fails if any topic
configuration file sets `cleanup.policy=compact` on a `cmd` topic.

#### F5.2 — Version component in consumer group IDs

**Rule**: All consumer group IDs must include a version component.

**Format**: `omniclaude-{node-name}-{version}`

**Examples**:
- `omniclaude-compliance-subscriber.v1` ✓
- `omniclaude-git-effect.v1` ✓
- `omniclaude-compliance` ✗ (missing version)
- `omniclaude-git` ✗ (missing version)

**Rationale**: Encoding the schema version in the consumer group ID prevents
silent schema drift. When the event schema changes incompatibly, bumping the
version creates a new consumer group, forcing a clean offset from the start
of the retention window.

#### F5.3 — Offset reset requires version bump

**Rule**: Any consumer group offset reset (e.g., `auto.offset.reset=earliest` /
`--from-beginning`) requires an explicit version bump in the consumer group ID.

**Enforcement**: `FatalStartupError` raised at consumer startup if
`auto.offset.reset=earliest` is configured and the group ID does not contain
a version component suffix (pattern: `\\.v\\d+$`).

**Bypass**: Only permitted during initial cluster bootstrap (no committed offsets
exist for the group). The startup guard checks for existing offsets before failing.

#### F5.4 — Naming convention for skill node consumers

**Rule**: All new skill node consumers added as part of the autonomous skill
platform (OMN-2591) must follow the naming convention:

```
omniclaude-{node-name}-{version}
```

**Skill node consumers** (6 new nodes from OMN-2593):

| Node | Consumer Group ID |
|------|-------------------|
| NodeGitEffect | `omniclaude-git-effect.v1` |
| NodeClaudeCodeSessionEffect | `omniclaude-claude-code-session-effect.v1` |
| NodeLocalLlmInferenceEffect | `omniclaude-local-llm-inference-effect.v1` |
| NodeLinearEffect | `omniclaude-linear-effect.v1` |
| NodeTicketingEffect | `omniclaude-ticketing-effect.v1` |
| NodeLocalCodingOrchestrator | `omniclaude-local-coding-orchestrator.v1` |

---

## Implementation Status

| Rule | Status | Ticket |
|------|--------|--------|
| F5.1 compact cmd check | CI script added | OMN-2595 |
| F5.2 version in group ID | Documented + validator | OMN-2595 |
| F5.3 offset reset guard | `FatalStartupError` added | OMN-2595 |
| F5.4 skill node naming | Constants added | OMN-2595 |
