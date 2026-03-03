---
name: feature-dashboard
description: Audit skill connectivity across 8 layers and surface gaps as actionable, machine-readable output. Supports audit (read-only) and ticketize (create Linear tickets for gaps) modes.
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags:
  - audit
  - skills
  - connectivity
  - dashboard
  - omniclaude
args:
  - name: mode
    description: "audit | ticketize (default: audit)"
    default: audit
  - name: format
    description: "cli | markdown | web | all (default: cli; audit mode only)"
    default: cli
  - name: output-dir
    description: "file output dir (default: docs/feature-dashboard)"
    default: docs/feature-dashboard
  - name: filter-skill
    description: "limit to one skill (kebab-case)"
  - name: filter-status
    description: "wired | partial | broken | unknown | all (default: all)"
    default: all
  - name: fail-on
    description: "broken | partial | any (default: unset)"
  - name: team
    description: "Linear team (ticketize mode only; default: OmniNode)"
    default: OmniNode
  - name: online
    description: "true | false (default: false); verify Linear ticket existence via API (audit only)"
    default: "false"
ticket: OMN-3498
---

# Feature Dashboard

Provides an automated audit of every skill's connectivity across 8 layers and surfaces gaps as actionable, machine-readable output. Audit and mutation are strictly separated.

## Modes

### `audit` mode (read-only)

1. Announce: "Running feature-dashboard audit."
2. Discover skills: directories under `plugins/onex/skills/` where name does NOT start with `_` AND `SKILL.md` exists. Sort by name.
3. For each skill, determine `node_type` (from `contract.yaml`, or "unknown"), apply applicability matrix, run applicable checks. Populate `evidence` for every check result.
4. Build `ModelFeatureDashboardResult`. Compute `failed`/`fail_reason` from `--fail-on` if set.
5. **Always** write `{output_dir}/feature-dashboard.stable.json` (sorted keys, no `generated_at`).
6. Render additional formats per `--format`.
7. If `--fail-on` threshold exceeded: exit non-zero.

### `ticketize` mode (separate invocation, mutates)

1. Announce: "Running feature-dashboard ticketize."
2. Load and validate `{output_dir}/feature-dashboard.stable.json`. Fail immediately if absent or invalid.
3. For each skill where `status` is `partial` or `broken`: create one Linear ticket listing gaps with `suggested_fix`.

## Connectivity Checks

| Check | Applies to | Severity |
|-------|-----------|----------|
| `skill_md` | All skills | CRITICAL |
| `orchestrator_node` | All skills | CRITICAL |
| `contract_yaml` | All skills | CRITICAL |
| `event_bus_present` | Orchestrator nodes only | HIGH |
| `topics_nonempty` | Event-driven orchestrators only | HIGH |
| `topics_namespaced` | Event-driven orchestrators only | HIGH |
| `test_coverage` | All skills | MEDIUM |
| `linear_ticket` | All skills | LOW |

## Status Rollup

- Any CRITICAL or HIGH fail → `broken`
- All CRITICAL/HIGH pass, any MEDIUM/LOW fail or WARN → `partial`
- All applicable checks PASS → `wired`
- Could not read key files → `unknown`

## Stable JSON

Always written to `{output_dir}/feature-dashboard.stable.json`:
- Excludes `generated_at` field
- Keys sorted deterministically (`sort_keys=True`)
- Skills sorted alphabetically
- Byte-stable across runs (idempotent)
