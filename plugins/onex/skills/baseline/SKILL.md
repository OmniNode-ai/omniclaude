---
description: Capture and compare system state baselines using node_baseline_capture and node_baseline_compare
mode: full
version: 2.0.0
level: basic
debug: false
category: observability
tags:
  - baseline
  - measurement
  - snapshot
  - overnight
  - delta
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: subcommand
    description: "Action: capture, compare, or report"
    required: true
  - name: baseline_id
    description: "Unique baseline identifier (e.g. overnight-2026-04-09)"
    required: true
  - name: --probes
    description: "Comma-separated probe list (default: github_prs,linear_tickets,system_health,git_branches)"
    required: false
  - name: --label
    description: "Human-readable label for this baseline"
    required: false
---

# /baseline -- Baseline Measurement Skill

**Skill ID**: `onex:baseline`
**Version**: 2.0.0
**Backing nodes**: `node_baseline_capture`, `node_baseline_compare`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-12224). All logic in `node_baseline_capture` and `node_baseline_compare`. Replaced direct Python handler imports with `onex run-node` dispatch.
- **1.0.0** — Original skill with direct Python handler imports.

## Usage

```
/baseline capture [baseline_id] [--probes pr,tickets,health] [--label "description"]
/baseline compare [baseline_id] [--probes pr,tickets]
/baseline report [baseline_id]
```

**Announce at start:** "I'm using the baseline skill."

## Behavior

### capture

Dispatches `node_baseline_capture` to snapshot current system state.

```bash
uv run onex run-node node_baseline_capture --input '{
  "baseline_id": "<baseline_id>",
  "probes": ["github_prs", "linear_tickets", "system_health", "git_branches"],
  "label": "<label>",
  "dry_run": false
}'
```

- Terminal event: `onex.evt.omnimarket.baseline-captured.v1`
- Artifact written to: `.onex_state/baselines/{baseline_id}.json`
- Reports: probes run, probes failed, artifact path

### compare

Dispatches `node_baseline_compare` to load the baseline artifact, re-capture current state, and diff per probe.

```bash
uv run onex run-node node_baseline_compare --input '{
  "baseline_id": "<baseline_id>",
  "dry_run": false
}'
```

- Terminal event: `onex.evt.omnimarket.baseline-compared.v1`
- Artifact written to: `.onex_state/baselines/{baseline_id}.delta.json`
- Reports: summary paragraph + per-probe delta counts table

### report

Reads existing `.delta.json` artifact and displays in chat. No re-capture. No dispatch needed — read the artifact directly from `.onex_state/baselines/{baseline_id}.delta.json`.

## Default Probes

`github_prs`, `linear_tickets`, `system_health`, `git_branches`

Optional (require infra): `kafka_topics`, `db_row_counts`

## Example -- Overnight Workflow

Before work:

```
/baseline capture overnight-2026-04-09 --label "before overnight run"
```

After work:

```
/baseline compare overnight-2026-04-09
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

### capture

Contract target: `node_baseline_capture`

Command topic: `onex.cmd.omnimarket.baseline-capture-start.v1`

Terminal event: `onex.evt.omnimarket.baseline-captured.v1`

### compare

Contract target: `node_baseline_compare`

Command topic: `onex.cmd.omnimarket.baseline-compare-start.v1`

Terminal event: `onex.evt.omnimarket.baseline-compared.v1`

## Architecture

```
SKILL.md   -> dispatch-only shim (this file)
capture    -> omnimarket/src/omnimarket/nodes/node_baseline_capture/
compare    -> omnimarket/src/omnimarket/nodes/node_baseline_compare/
contracts  -> node_baseline_capture/contract.yaml, node_baseline_compare/contract.yaml
```
