---
version: 2.0.0
description: 'Detect duplicate definitions across repos: Drizzle table definitions, Kafka topic registrations,
  migration prefixes, and Python model names. Returns structured findings for autopilot halt decisions.
  Dispatches to node_duplication_sweep (omnimarket).

  '
mode: full
user_invocable: true
level: advanced
debug: false
tags:
  - sweep
  - quality
  - enforcement
  - dispatch-only
  - routing-enforced
skill_kind: dispatch
args:
  - name: --omni-home
    description: string arg
    required: false
  - name: --checks
    description: string list arg
    required: false
---

# /onex:duplication_sweep — one command, one typed result

**Skill ID**: `onex:duplication_sweep` · **Command**: `uv run onex skill duplication_sweep` (omnibase_infra) · **Backing node**: `node_duplication_sweep` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[DuplicationSweepResult]` JSON to
stdout carrying the FULL handler result; RuntimeLocal logs and intermediate
context go to a capture file + the artifact store, never to you.

See `prompt.md` for the one command and how to present the typed result.

## What this skill does NOT do

- Construct a payload file, `cd` anywhere, or `cat` a workflow_result.json (all internal to `onex skill`)
- Run any inline scan, probe, or orchestration — the backing node owns all logic
- Contain executable logic in this directory — markdown only

## Related

- **CLI entrypoint**: `omnibase_infra/src/omnibase_infra/cli/cli_skill.py`
- **Skill→node mapping**: `omnibase_infra/src/omnibase_infra/cli/skill_mapping.yaml`
- **Result model**: `omnimarket.nodes.node_duplication_sweep.handlers.handler_duplication_sweep.DuplicationSweepResult`
