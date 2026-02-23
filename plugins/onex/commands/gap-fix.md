---
name: gap-fix
description: Auto-fix loop for gap-analysis findings
tags: [gap-analysis, auto-fix, pipeline]
---

# Gap Fix

**Usage:** `/gap-fix [flags]`

Automates the "detected to fixed" loop for gap-analysis findings. Classifies findings by
auto-dispatch eligibility, dispatches `ticket-pipeline` for safe-only findings, then calls
`pr-queue-pipeline --prs` on the created PRs.

## Implementation

When invoked, execute the gap-fix skill:

```
Invoke: Skill(skill="onex:gap-fix", args="$ARGUMENTS")
```

Pass all user-provided flags through as `$ARGUMENTS`.

## Examples

```
/gap-fix --latest                          # Fix findings from most recent gap-analysis run
/gap-fix --report multi-epic-2026-02-23/run-001
/gap-fix --ticket OMN-2500                 # Single finding via Linear ticket marker block
/gap-fix --dry-run                         # Classify + print plan, no side effects
/gap-fix --choose GAP-b7e2d5f8=A          # Provide decision for a gated finding
/gap-fix --mode implement-only            # Implement fixes directly, no ticket-pipeline
```
