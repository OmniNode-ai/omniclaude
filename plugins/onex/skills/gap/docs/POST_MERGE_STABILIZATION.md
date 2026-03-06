# Post-Merge Stabilization Workflow

After merging cross-repo changes from an epic, use this 6-step workflow to detect and
resolve integration gaps before they reach production.

## When to Run

- After all PRs for an epic have been merged
- Before deploying merged changes to staging or production
- When resuming stabilization after a partial fix cycle

## Prerequisites

- All PRs for the epic are merged to `main`
- Infrastructure services are running (Kafka, PostgreSQL, Qdrant)
- `~/.omnibase/.env` is sourced with current credentials

## Workflow

### Step 1: Detect Integration Gaps

Run the gap detection probe across all repos touched by the epic.

```
/gap detect --epic OMN-XXXX
```

This produces a report at `~/.claude/gap-analysis/{epic_id}/{run_id}.json` and `.md`.
The detect phase runs all 11 probe categories and emits findings with fingerprints,
confidence levels, and severity ratings.

**Expected output**: A summary listing DETERMINISTIC and BEST_EFFORT findings, skipped
probes, and a link to the full report.

### Step 2: Review Findings

Open the markdown report and review each finding:

- **CRITICAL findings**: Must be resolved before deployment.
- **WARNING findings**: Should be resolved; may be deferred with justification.
- **BEST_EFFORT findings**: Review for false positives. Suppress if not actionable.
- **SKIP findings**: Informational only; input data was absent for that probe.

Identify which findings can be auto-fixed and which require human decisions (GATE).

### Step 3: Auto-Fix Eligible Findings

Run the fix subcommand to auto-dispatch fixes for eligible findings.

```
/gap fix --latest
```

This classifies findings into AUTO and GATE categories, dispatches `ticket-pipeline`
for AUTO findings, and creates PRs. GATE findings emit decision blocks for human input.

**If all findings are GATE**: The skill returns `status: gate_pending`. Provide decisions
via `--choose` and re-run (see Step 4).

### Step 4: Resolve GATE Findings

For each GATE finding, review the decision options and provide choices:

```
/gap fix --latest --choose GAP-b7e2d5f8=A,GAP-c3a1e2d4=B
```

Choices are persisted in `decisions.json` so they are not re-prompted on subsequent runs.
Use `--force-decide` to re-open a previously decided finding.

**Common decision patterns**:
- **Option A**: Apply the recommended fix (most common).
- **Option B**: Add to `suppressions.yaml` (intentional divergence, document the reason).
- **Option C**: Skip this run (defer to a future stabilization cycle).

### Step 5: Verify Fixes

Run the cycle subcommand with `--resume` and `--verify` to re-probe fixed findings
and optionally run the golden-path verification.

```
/gap cycle --resume --verify
```

This re-runs the minimal probes for each fixed finding to confirm the legacy patterns
are gone, then runs `golden-path-validate` to verify end-to-end routing still works.

**If re-probe fails**: The finding is marked `still_open` and must be addressed manually.

### Step 6: Ticket Remaining Failures

Any findings that remain after Steps 3-5 (re-probe failures, deferred GATE decisions,
infra blockers) become Linear tickets for manual resolution.

The gap skill automatically creates tickets for unresolved findings during the fix phase.
Review the created tickets and prioritize them in the current or next sprint.

```
# View created tickets
/gap fix --latest --dry-run
```

## Quick Reference

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `/gap detect --epic OMN-XXXX` | Scan for integration gaps |
| 2 | Review `~/.claude/gap-analysis/{epic_id}/{run_id}.md` | Assess findings |
| 3 | `/gap fix --latest` | Auto-fix eligible findings |
| 4 | `/gap fix --latest --choose GAP-id=A,...` | Resolve GATE findings |
| 5 | `/gap cycle --resume --verify` | Verify fixes and run golden path |
| 6 | Review Linear tickets for remaining failures | Manual resolution |

## Resuming an Interrupted Workflow

If the workflow is interrupted at any step, resume from the last completed phase:

```
/gap cycle --resume ~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json
```

The cycle subcommand reads `summary.json` to determine which phases have completed
and resumes from the first incomplete phase.

## Integration with Epic Lifecycle

```
Epic PRs merged
      |
      v
Step 1: /gap detect --epic OMN-XXXX
      |
      v
Step 2: Review findings report
      |
      v
Step 3: /gap fix --latest (auto-fix)
      |
      v
Step 4: /gap fix --latest --choose ... (resolve gates)
      |
      v
Step 5: /gap cycle --resume --verify (verify + golden path)
      |
      v
Step 6: Remaining failures -> Linear tickets
      |
      v
Deploy to staging/production
```
