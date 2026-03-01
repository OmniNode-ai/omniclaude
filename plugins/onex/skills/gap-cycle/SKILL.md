---
name: gap-cycle
description: >
  Orchestrate the gap investigation loop: detect (gap-analysis) →
  fix (gap-fix) → verify (golden-path-validate routing, optional).
  Single entry point replacing manual sub-skill chaining. v0.1.
version: 0.1.0
category: workflow
tags:
  - gap-analysis
  - integration
  - orchestration
  - fix
composable: false
args:
  - name: --epic
    description: "Linear epic ID to analyze. XOR with --report and --resume."
    required: false
  - name: --report
    description: >
      Path to an existing gap-analysis .json report. Skips Phase 1.
      epic_id must be present in report metadata; hard error if missing.
    required: false
  - name: --resume
    description: >
      Path to a prior gap-cycle summary.json. Continues from the first
      phase where phase_results[phase] is null and phases_executed[phase]
      is true.
    required: false
  - name: --audit
    description: >
      v0.1: Records that pipeline-audit was requested and emits a reminder
      to run it manually. Does not chain pipeline-audit automatically.
      v0.2 will add automatic chaining. Default: off.
    required: false
  - name: --no-fix
    description: "Skip gap-fix (Phase 3). Default: fix is ON."
    required: false
  - name: --verify
    description: >
      Run golden-path-validate (Phase 4) using the canonical routing
      golden path. Default: off. Requires a redeploy confirmation gate
      (Phase 3.5) before execution.
    required: false
  - name: --auto-only
    description: >
      Pass to gap-fix: skip GATE findings. If ALL findings are gated,
      composite_status=gate_pending and Phase 4 is skipped.
    required: false
  - name: --dry-run
    description: >
      No writes to Linear/GitHub/external services. Local artifact files
      (report, gap-fix-output.json, summary.json) are still written.
      gap-fix receives --dry-run (plan mode only). golden-path-validate
      is suppressed entirely.
    required: false
outputs:
  - name: summary.json
    type: file
    description: >
      Written to ~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json.
      Contains phase results, PRs created, gated findings count,
      nothing_to_fix flag, composite_status, and dry_run flag.
    fields:
      - epic_id: string
      - run_id: string        # "gap-cycle-{YYYY-MM-DDThh:mm:ss}Z" (UTC)
      - source_report_path: string
      - phases_executed: object  # {detect, audit, fix, verify}: bool
      - phase_results: object    # per-phase status + artifact + counts (null if skipped)
      - prs_created: array       # [{repo, number, url}]
      - gated_findings_count: integer
      - nothing_to_fix: bool
      - composite_status: string  # see status_values
      - dry_run: bool
status_values:
  complete: >
    All enabled phases ran AND gated_findings_count == 0 AND
    (verify not enabled OR verify passed). OR nothing_to_fix=true.
  partial: >
    Some phases skipped by flags; OR verify not enabled; OR
    gated_findings_count > 0 (some findings unresolved).
  gate_pending: >
    --auto-only: all gap-fix findings were gated, zero PRs created.
    Phase 4 skipped.
  blocked: >
    Required prerequisite missing — report not found, epic_id absent
    from report metadata. No exception crash.
  error: >
    Exception or tool failure in any phase.
---

## Usage

```bash
# Minimal: detect + fix (default)
gap-cycle --epic OMN-XXXX

# Detect only (no fix)
gap-cycle --epic OMN-XXXX --no-fix

# Detect + fix + single routing verify
gap-cycle --epic OMN-XXXX --verify

# Skip detect (use existing report)
gap-cycle --report ~/.claude/gap-analysis/OMN-XXXX/<run_id>.json

# Resume interrupted run
gap-cycle --resume ~/.claude/gap-cycle/OMN-XXXX/<run_id>/summary.json

# Dry run (no external writes, local files written)
gap-cycle --epic OMN-XXXX --dry-run
```

## Artifact Chaining

gap-cycle requires stdout markers from sub-skills. If a marker is absent,
gap-cycle emits a hard error — it does NOT reconstruct paths from naming
conventions or check fallback pointer files.

- **gap-analysis** must emit: `ARTIFACT: <absolute path>`
- **gap-fix** must emit: `GAP_FIX_OUTPUT: <absolute path>`

Both markers must appear on ALL exit paths (see Tasks 1 and 2 for required changes).

## v0.2 Roadmap

- pipeline-audit chaining (Phase 2 automation)
- sidecar audit annotation files (no schema mutation)
- per-repo-to-pipeline verification mapping
