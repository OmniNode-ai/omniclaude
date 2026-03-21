# close-day

End-of-day reconciliation skill. Snapshots dashboard baselines, verifies
Kafka boundary parity, collects merged PRs, and produces a day close artifact.

## Context

You are the close-day orchestrator. Execute each phase sequentially. If a phase
fails, record the failure in the artifact and continue to the next phase.

## Inputs

- `date` (optional): ISO date string. Default: today.
- `skip-baseline` (optional): Skip Phase 1.
- `skip-boundary` (optional): Skip Phase 2.
- `dry-run` (optional): Print commands without executing.

## Phase 1: Snapshot Dashboard Baselines

Run the omnidash health check with baseline save:

```bash
uv run check-omnidash-health --save-baseline --json
```

This produces:
- A baseline file at `~/.omnibase/omnidash_baseline.json`
- JSON output with `tables_with_data`, `tables_empty`, `total_tables`

Capture the output. If the command fails (not installed, DB unreachable),
record `status: "error"` for this phase and continue.

If `--skip-baseline` was passed, record `status: "skipped"`.

## Phase 2: Verify Boundary Parity

Run the Kafka boundary parity check:

```bash
uv run check-boundary-parity --json
```

This produces JSON with `total_boundaries`, `mismatches`, `mismatch_details`.

If the command fails or `check-boundary-parity` is not available (PR #82 not
merged), record `status: "skipped"` with a note explaining PR #82 dependency.

If `--skip-boundary` was passed, record `status: "skipped"`.

## Phase 3: Collect Merged PRs

Run:

```bash
gh pr list --state merged --search "merged:$(date -u +%Y-%m-%d)" --json number,title,repository --limit 200
```

Group by repository. Count total and per-repo.

## Phase 4: Generate Day Close Artifact

Compute the overall status:
- `"clean"` -- baseline saved, no boundary mismatches, no errors
- `"warning"` -- boundary mismatches found OR any phase skipped
- `"failed"` -- baseline or boundary check errored

Write the artifact to:
```
$ONEX_CC_REPO_PATH/drift/day_close/{date}.yaml
```

Where `ONEX_CC_REPO_PATH` defaults to the onex_change_control repo path.
If running from a worktree, use the worktree path. Otherwise resolve from
the `OMNI_HOME` environment variable or the standard repo layout.

Artifact schema:

```yaml
# Day close artifact -- authoritative for next begin-day baseline comparison
generated_at: "2026-03-21T23:59:00Z"
date: "2026-03-21"
status: "clean"  # clean | warning | failed
baseline:
  status: "ok"  # ok | skipped | error
  snapshot_path: "~/.omnibase/omnidash_baseline.json"
  snapshot_hash: "sha256:..."  # sha256 of baseline file contents
  tables_with_data: 10
  tables_empty: 59
  total_tables: 69
  regressions_detected: 0
boundary_parity:
  status: "ok"  # ok | skipped | error
  total_boundaries: 49
  mismatches: 0
  mismatch_details: []
  note: null  # e.g., "check-boundary-parity not available (PR #82 not merged)"
merged_prs:
  count: 85
  repos:
    omniclaude: 9
    omnibase_infra: 25
    omnidash: 12
    omnibase_core: 5
    onex_change_control: 3
regressions:
  count: 0
  details: []
```

One file per day. Rerun overwrites the file for that date. Git history
preserves prior same-day artifact states.

## Phase 5: Commit

If not `--dry-run`:

1. `cd` to the onex_change_control repo
2. `git add drift/day_close/{date}.yaml`
3. `git commit -m "chore(close-day): day close artifact for {date} [OMN-5651]"`

Do NOT push -- the commit stays local for the next begin-day to read.

## Error Handling

- `check-omnidash-health` not installed: baseline status = "error", continue
- `check-boundary-parity` not installed: boundary status = "skipped", continue
- `gh` CLI not available: merged_prs = empty, continue
- DB not reachable: baseline status = "error", continue
- Any phase error: record in artifact, continue to next phase
- Never exit 1 unless the artifact YAML itself cannot be written

## Output

Print a summary table:

```
close-day summary for 2026-03-21
  baseline:        ok (10 tables with data, 59 empty)
  boundary parity: ok (49 boundaries, 0 mismatches)
  merged PRs:      85 across 5 repos
  status:          clean
  artifact:        onex_change_control/drift/day_close/2026-03-21.yaml
```
