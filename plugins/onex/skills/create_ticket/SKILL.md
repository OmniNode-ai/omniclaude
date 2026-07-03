---
description: Create a single Linear ticket from args, contract file, or plan milestone with conflict resolution
mode: full
version: 2.0.0
level: basic
debug: false
category: workflow
tags:
  - linear
  - tickets
  - automation
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: --title
    description: string arg
    required: false
  - name: --from-contract
    description: string arg
    required: false
  - name: --from-plan
    description: string arg
    required: false
  - name: --milestone
    description: string arg
    required: false
  - name: --repo
    description: string arg
    required: false
  - name: --parent
    description: string arg
    required: false
  - name: --blocked-by
    description: string list arg
    required: false
  - name: --project
    description: string arg
    required: false
  - name: --team
    description: string arg
    required: false
  - name: --allow-arch-violation
    description: boolean flag
    required: false
skill_kind: dispatch
---

# /onex:create_ticket — one command, one typed result

**Skill ID**: `onex:create_ticket` · **Command**: `uv run onex skill create_ticket` (omnibase_infra) · **Backing node**: `node_create_ticket` (omnimarket)

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[ModelCreateTicketResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_create_ticket.handlers.handler_create_ticket.ModelCreateTicketResult`
