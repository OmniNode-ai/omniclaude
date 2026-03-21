---
description: End-of-day reconciliation -- snapshot dashboard baselines, verify boundaries, generate day close artifact
mode: full
version: 1.0.0
level: advanced
debug: false
category: pipeline
tags:
  - close-day
  - baseline
  - reconciliation
  - daily-cycle
author: OmniClaude Team
composable: true
inputs:
  - name: date
    type: str
    description: ISO date to close (e.g. 2026-03-21); defaults to today
    required: false
  - name: skip-baseline
    type: bool
    description: Skip dashboard baseline snapshot
    required: false
  - name: skip-boundary
    type: bool
    description: Skip boundary parity check
    required: false
  - name: dry-run
    type: bool
    description: Print what would run without executing
    required: false
outputs:
  - name: artifact_path
    type: str
    description: Path to the day close YAML artifact
  - name: baseline_path
    type: str
    description: Path to the saved baseline JSON
---

# close-day Skill

> **OMN-5651** -- End-of-day reconciliation that pairs with `/begin-day`
> to form a daily OODA cycle.

## Overview

`/close-day` automates the evening reconciliation loop:

1. **Phase 1** -- Snapshot dashboard baselines via `check-omnidash-health --save-baseline`
2. **Phase 2** -- Verify Kafka boundary parity via `check-boundary-parity`
3. **Phase 3** -- Collect today's merged PRs
4. **Phase 4** -- Generate day close YAML artifact
5. **Phase 5** -- Commit the artifact

## Quick Start

```
/close-day
```

Or with options:

```
/close-day --skip-baseline
/close-day --skip-boundary
/close-day --dry-run
/close-day --date 2026-03-21
```

## Artifact Structure

```
onex_change_control/drift/day_close/
  {YYYY-MM-DD}.yaml    <-- one file per day, rerun overwrites
```

## Relationship to begin-day

```
/close-day (evening)
  |- snapshots dashboard row count baseline
  |- verifies Kafka boundary parity
  |- writes day_close YAML (authoritative for next begin-day)
  \- baseline file at ~/.omnibase/omnidash_baseline.json

/begin-day (morning)
  |- reads previous day's baseline
  |- compares current state against baseline
  \- flags regressions as CRITICAL findings
```

## Dependencies

- `onex_change_control` package: `check-omnidash-health`, `check-boundary-parity` entry points
- `gh` CLI: for merged PR collection
- `pyyaml`: for YAML serialization

## Files

| Path | Purpose |
|------|---------|
| `plugins/onex/skills/close_day/SKILL.md` | This file (descriptive) |
| `plugins/onex/skills/close_day/prompt.md` | Authoritative behavior specification |
| `plugins/onex/skills/close_day/topics.yaml` | Kafka topic manifest |
