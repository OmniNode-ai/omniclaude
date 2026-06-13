---
description: Detect AI-generated quality anti-patterns across all repos — phantom callables in skill markdown, backwards compat shims, prohibited env var patterns, hardcoded topic strings, hardcoded absolute paths and LAN IPs, agent-left TODO/FIXME markers, and empty implementations.
version: 3.1.0
mode: full
level: advanced
debug: false
category: quality
tags:
  - ai-quality
  - code-review
  - anti-patterns
  - org-wide
  - autonomous
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names (default: all supported repos)"
    required: false
  - name: --checks
    description: "Comma-separated check categories: phantom-callables,compat-shims,prohibited-patterns,hardcoded-topics,hardcoded-paths,todo-fixme,todo-stale,empty-impls (default: all)"
    required: false
  - name: --dry-run
    description: Scan and report only — no tickets, no fixes
    required: false
  - name: --ticket
    description: Create Linear tickets for findings above severity threshold
    required: false
  - name: --severity-threshold
    description: "Minimum severity to act on: WARNING | ERROR (default: WARNING)"
    required: false
inputs:
  - name: repos
    description: "list[str] — repos to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult JSON; aislop-specific findings (by severity and check) are delivered in the model's output field"
skill_kind: dispatch
---

# /onex:aislop_sweep — one command, one typed result

**Skill ID**: `onex:aislop_sweep` · **Command**: `uv run onex skill aislop_sweep` (omnibase_infra) · **Backing node**: `node_aislop_sweep` (omnimarket) · **Ticket**: OMN-13097

A dispatch skill IS one CLI call. Payload construction, node dispatch, and
result extraction all live in the `onex skill` entrypoint (declarative
`skill_mapping.yaml` registry) — there is no procedure to learn here. The
command prints exactly one typed `ModelSkillResult[AislopSweepResult]` JSON to
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
- **Result model**: `omnimarket.nodes.node_aislop_sweep.handlers.handler_aislop_sweep.AislopSweepResult`
