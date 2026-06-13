---
description: Scan documentation files across repos for broken references, stale content, and CLAUDE.md accuracy. Generates freshness reports and optionally creates Linear tickets for broken/stale docs.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: quality
tags:
  - documentation
  - freshness
  - scanning
  - quality
  - claude-md
  - cross-reference
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repo
    description: "Scan a single repo by name"
    required: false
  - name: --claude-md-only
    description: "Only check CLAUDE.md files (faster, used in close-out autopilot)"
    required: false
  - name: --broken-only
    description: "Only report broken references (skip stale)"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for broken/stale docs"
    required: false
  - name: --max-tickets
    description: "Max tickets to create per run (default: 10)"
    required: false
  - name: --dry-run
    description: "Report only, no ticket creation"
    required: false
skill_kind: dispatch
---

# /onex:doc_freshness_sweep — one command, one typed result

**Skill ID**: `onex:doc_freshness_sweep` · **Command**: `uv run onex skill doc_freshness_sweep` (omnibase_infra) · **Backing node**: `node_doc_freshness_sweep` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[DocFreshnessSweepResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_doc_freshness_sweep.handlers.handler_doc_freshness_sweep.DocFreshnessSweepResult`
