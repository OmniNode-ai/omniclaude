---
description: Capture and compare system state baselines using node_baseline_capture and node_baseline_compare
mode: full
version: 1.0.0
level: basic
debug: false
category: observability
tags:
  - baseline
  - measurement
  - snapshot
  - overnight
  - delta
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

Capture and compare system state baselines using `node_baseline_capture` and `node_baseline_compare`.

## Usage

```
/baseline capture [baseline_id] [--probes pr,tickets,health] [--label "description"]
/baseline compare [baseline_id] [--probes pr,tickets]
/baseline report [baseline_id]
```

## Behavior

### capture

Runs `node_baseline_capture` to snapshot current system state.

- Emits: `onex.cmd.omnimarket.baseline-capture-start.v1`
- Artifact written to: `.onex_state/baselines/{baseline_id}.json`
- Reports: probes run, probes failed, artifact path

### compare

Loads baseline artifact, re-captures current state, diffs per probe.

- Emits: `onex.cmd.omnimarket.baseline-compare-start.v1`
- Artifact written to: `.onex_state/baselines/{baseline_id}.delta.json`
- Reports: summary paragraph + per-probe delta counts table

### report

Reads existing `.delta.json` artifact and displays in chat. No re-capture.

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

## Implementation

The skill delegates to two omnimarket compute nodes:

- `node_baseline_capture` -- captures named system state snapshot with pluggable probes
- `node_baseline_compare` -- loads baseline artifact, re-probes, computes structured delta

Both nodes are zero-infra capable (EventBusInmemory, filesystem-only artifacts).
Probe failures are non-fatal; the capture proceeds with available data.
