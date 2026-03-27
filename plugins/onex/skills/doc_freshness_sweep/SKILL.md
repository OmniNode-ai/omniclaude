---
description: Scan documentation files across repos for broken references, stale content, and CLAUDE.md accuracy. Generates freshness reports and optionally creates Linear tickets for broken/stale docs.
mode: full
version: 1.0.0
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
author: OmniClaude Team
composable: true
inputs:
  - name: repo
    type: str
    description: "Repo name to scan (default: all repos under omni_home)"
    required: false
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
    description: "Maximum tickets to create (default: 10)"
    required: false
  - name: --dry-run
    description: "Preview findings without creating tickets"
    required: false
---

# Doc Freshness Sweep

Scan documentation files across ONEX platform repos for broken references, stale content, and CLAUDE.md accuracy.

## What This Skill Does

1. **Scan** all `.md` files across specified repos (default: all repos under `omni_home/`)
2. **Extract** code references: file paths, class/function names, commands, URLs, env vars
3. **Resolve** each reference to check if the target still exists
4. **Detect staleness** by comparing doc modification dates against referenced code dates
5. **Cross-validate** CLAUDE.md instructions (commands, paths, conventions, tables)
6. **Generate** a `ModelDocFreshnessSweepReport` with per-repo breakdowns
7. **Save** report to `docs/registry/doc-freshness-<date>.json`
8. **Optionally create** Linear tickets for broken/stale docs

## Exclusions

- `docs/history/` (historical, intentionally frozen)
- `node_modules/`, `.git/`, `__pycache__/`, `.venv/`
- Lines annotated with `<!-- no-freshness-check -->`

## Execution Steps

### Phase 1: Discovery

```
For each repo in scan list:
  1. Find all .md files (excluding history/node_modules/.git)
  2. Extract references using doc_reference_extractor
  3. Resolve references using doc_reference_resolver
```

### Phase 2: Staleness Detection

```
For each repo:
  1. Get recently changed files (git log --since=30 days)
  2. For each doc, detect stale references
  3. Compute staleness score and assign verdict
```

### Phase 3: CLAUDE.md Cross-Reference (if not --broken-only)

```text
For each repo:
  1. Find CLAUDE.md
  2. Extract and resolve all file paths, commands, and conventions
  3. Report broken paths, invalid commands, stale conventions
```

### Phase 4: Report Generation

```
1. Aggregate per-doc results into ModelDocFreshnessSweepReport
2. Sort top_stale_docs by staleness score
3. Save JSON report to docs/registry/
4. Print human-readable summary
```

### Phase 5: Ticket Creation (if --create-tickets)

```
For each doc with BROKEN verdict:
  1. Check if ticket already exists for this doc path
  2. Create Linear ticket with broken references and line numbers
  3. Label: doc-freshness

For each doc with STALE verdict (up to --max-tickets):
  1. Create Linear ticket with staleness details
  2. Label: doc-freshness
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--repo <name>` | all | Scan single repo |
| `--claude-md-only` | false | Only check CLAUDE.md files |
| `--broken-only` | false | Only report broken references |
| `--create-tickets` | false | Create Linear tickets |
| `--max-tickets` | 10 | Max tickets to create |
| `--dry-run` | false | Preview without creating tickets |

## Output

### JSON Report

Saved to `docs/registry/doc-freshness-<YYYY-MM-DD>.json` in the `omni_home` repo.

### Console Summary

```
=== Doc Freshness Sweep ===
Repos scanned: 10
Total docs: 142
  Fresh: 108 (76%)
  Stale: 22 (15%)
  Broken: 8 (6%)
  Unknown: 4 (3%)

Top stale docs:
  1. omnibase_infra/CLAUDE.md (score: 0.72)
  2. docs/design/DEPLOY_GUIDE.md (score: 0.65)
  ...

Broken references: 15
Stale references: 34
```

## Integration

- Used by close-out autopilot (--claude-md-only mode)
- Emits `onex.evt.onex-change-control.doc-freshness-swept.v1` event
- Reports consumed by omnidash `/status` page Doc Freshness card

## External Dependencies

This skill depends on modules from the `onex_change_control` package:

- `onex_change_control.scanners.doc_reference_extractor` — pattern matching for file paths, class names, function names, shell commands, URLs, env vars
- `onex_change_control.scanners.doc_reference_resolver` — resolves extracted references against the codebase
- `onex_change_control.scanners.doc_staleness_detector` — staleness scoring and verdict assignment
- `onex_change_control.models.model_doc_freshness_sweep_report.ModelDocFreshnessSweepReport` — report output model
- Event schema `onex.evt.onex-change-control.doc-freshness-swept.v1` is owned by `onex_change_control`
