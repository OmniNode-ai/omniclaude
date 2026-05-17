---
version: 2.0.0
description: >
  Detect duplicate definitions across repos: Drizzle table definitions,
  Kafka topic registrations, migration prefixes, and Python model names.
  Returns structured findings for autopilot halt decisions.
  Dispatches to node_duplication_sweep (omnimarket).
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
---

# /onex:duplication_sweep — Duplicate Definition Sweep

**Skill ID**: `onex:duplication_sweep`
**Version**: 2.0.0
**Backing node**: `node_duplication_sweep`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). Removed inline check implementations from prompt.md.
- **1.0.0** — Original (OMN-10431).

## What this skill does

Dispatches through `onex run-node node_duplication_sweep`. The node owns all scanning
logic (D1–D4). This shim is a thin shell: parse args, dispatch, render results.

**Announce at start:** "I'm using the duplication-sweep skill."

## Dispatch

```bash
uv run onex run-node node_duplication_sweep --input '{
  "omni_home": null,
  "checks": ["D1", "D2", "D3", "D4"]
}'
```

Omit `omni_home` or `checks` to use defaults.

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_duplication_sweep`

Command topic: `onex.cmd.omnimarket.duplication-sweep-start.v1`

Terminal event: `onex.evt.omnimarket.duplication-sweep-completed.v1`

## Usage

```
/duplication-sweep [--checks D1,D2] [--omni-home /path] [--json]
```
