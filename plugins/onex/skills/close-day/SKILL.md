---
name: close-day
description: Auto-generates a ModelDayClose YAML from today's GitHub PRs, git activity, and invariant probes
version: 1.0.0
category: workflow
tags:
  - day-close
  - drift-detection
  - invariants
  - reporting
author: OmniClaude Team
composable: false
inputs:
  - name: date
    type: str
    description: ISO date to close (e.g. 2026-02-28); defaults to today
    required: false
outputs:
  - name: yaml_path
    type: str
    description: Path where the day-close YAML was written (or "printed" if ONEX_CC_REPO_PATH not set)
---

# close-day Skill

> **CDQA-04 / OMN-2981** — Auto-generates a `ModelDayClose` YAML from today's GitHub PRs,
> git activity, and invariant probes.

## Overview

`close-day` closes out a development day by:

1. Pulling all merged PRs across the OmniNode-ai GitHub org for today
2. Fetching the active-sprint Linear plan (OMN-XXXX tickets)
3. Building `actual_by_repo` grouped by repo with OMN-XXXX references
4. Detecting **scope drift**: PRs with no matching OMN-XXXX ref → `drift_detected` entry
5. Running `scripts/check_arch_invariants.py` (shared with CDQA-07 / OMN-2977) to probe reducers/orchestrators
6. Detecting **golden-path progress** by reading `emitted_at` from `~/.claude/golden-path/TODAY/` artifact JSON files
7. Setting unknown statuses to `"unknown"` and adding entries to `corrections_for_tomorrow`
8. Validating the assembled dict against `ModelDayClose.model_validate()` (fails loudly on schema mismatch)
9. Writing to `$ONEX_CC_REPO_PATH/drift/day_close/YYYY-MM-DD.yaml` or printing with a warning banner

## Quick Start

```
/close-day
```

Or with explicit date:

```
/close-day --date 2026-02-28
```

## ONEX_CC_REPO_PATH Behavior

| `ONEX_CC_REPO_PATH` | Behavior |
|---------------------|----------|
| **Not set** | Generates YAML, prints with `⚠️ ONEX_CC_REPO_PATH not set — commit manually` banner. File is NOT written. |
| **Set, path exists** | Writes to `$ONEX_CC_REPO_PATH/drift/day_close/YYYY-MM-DD.yaml` |
| **Set, path missing** | Prints error + falls back to print-with-banner |

## Invariant Probes

Uses `scripts/check_arch_invariants.py` from CDQA-07 (OMN-2977). Does NOT reimplement the check.

- Probes `reducers_pure` and `orchestrators_no_io` across all repos in omni_home
- If the script is missing or a repo is not checked out → `status: unknown` + correction entry
- `effects_do_io_only` → always `unknown` (not checkable via AST scan)

## Golden Path Detection

Reads `~/.claude/golden-path/YYYY-MM-DD/*.json` for artifacts where:
- `artifact.status == "pass"` AND
- `artifact.emitted_at` starts with today's ISO date

Does NOT use directory creation time or directory name alone.

## Drift Detection

PRs with no OMN-XXXX ref in title or branch name → `drift_detected` entry with `category: scope`.

## Unknown Handling

Any probe that cannot determine status → `status: unknown` + actionable entry in `corrections_for_tomorrow`.

## Files

| Path | Purpose |
|------|---------|
| `plugins/onex/skills/close-day/SKILL.md` | This file (descriptive) |
| `plugins/onex/skills/close-day/prompt.md` | Authoritative behavior specification |
| `plugins/onex/skills/close-day/close_day.py` | Core logic module (importable for tests) |
| `tests/unit/skills/test_close_day.py` | Unit test suite (30 tests) |

## Dependencies

- `onex_change_control` package: `ModelDayClose`, `ModelTicketContract`
- `scripts/check_arch_invariants.py` (CDQA-07): AST-based invariant scanner
- `gh` CLI: for fetching GitHub PRs
- Linear MCP: for fetching sprint plan (optional)
- `pyyaml`: for YAML serialization

## Definition of Done

- [x] All unit tests pass (30 tests)
- [x] Uses `check_arch_invariants.py` from CDQA-07 (not a separate implementation)
- [x] Golden path detection uses `emitted_at` field in artifact JSON (not dir creation time)
- [x] Unknown invariants → `status: unknown` + entry in `corrections_for_tomorrow`
- [x] Output validates against `ModelDayClose.model_validate()` before writing/printing
- [x] `ONEX_CC_REPO_PATH` not set → banner printed, file not written
