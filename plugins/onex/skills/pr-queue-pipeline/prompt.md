# PR Queue Pipeline v1 Orchestration

You are the pr-queue-pipeline orchestrator. This prompt defines the complete v1 execution logic.
v1 adds Phase 1 (`review-all-prs`) before the fix phase. Use `--skip-review` for v0 behavior.

## Initialization

When `/pr-queue-pipeline [args]` is invoked:

1. **Announce**: "I'm using the pr-queue-pipeline skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--skip-review` — default: false
   - `--skip-fix` — default: false
   - `--dry-run` — default: false
   - `--run-id <id>` — default: none (resume mode when provided)
   - `--authors <list>` — default: all
   - `--max-total-prs <n>` — default: 20
   - `--max-total-merges <n>` — default: 10
   - `--max-parallel-prs <n>` — default: 5
   - `--merge-method <method>` — default: squash
   - `--allow-force-push` — default: false
   - `--slack-report` — default: false
   - `--max-parallel-repos <n>` — default: 3
   - `--clean-runs <n>` — default: 2
   - `--max-review-minutes <n>` — default: 30

3. **Generate or resume run_id**:
   - If `--run-id` provided: load ledger from `~/.claude/pr-queue/runs/<run_id>/ledger.json`
     and log: "Resuming from phase: <next_phase>" where next_phase is the first phase
     NOT in `phase_completed`. Skip all phases listed in `phase_completed`.
   - If `--dry-run` AND `--run-id` provided: read-only mode — print plan only, do NOT
     update ledger mtime, do NOT emit heartbeat, zero mutations.
   - Otherwise: generate new run_id `<YYYYMMDD-HHMMSS>-<random6>` (e.g., `20260223-143012-a3f`)
     and create ledger at `~/.claude/pr-queue/runs/<run_id>/ledger.json`.

4. **Print header**:
   ```
   PR Queue Pipeline v1 — run <run_id>
   Scope: <repos or "all"> | Authors: <authors or "all">
   Review phase: <enabled | --skip-review>
   ```

---

## Phase 0: Scan + Classify + Build Plan

Scan all repos in scope. For each repo (up to `--max-parallel-repos` concurrently):

```bash
gh pr list \
  --repo <repo> \
  --state open \
  --json number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,headRefOid,author \
  --limit 100
```

Apply predicates to classify each PR:

```python
def is_merge_ready(pr):
    return (
        pr["mergeable"] == "MERGEABLE"
        and is_green(pr)
        and pr.get("reviewDecision") in ("APPROVED", None)
    )

def needs_work(pr):
    return (
        pr["mergeable"] == "CONFLICTING"
        or not is_green(pr)
        or pr.get("reviewDecision") == "CHANGES_REQUESTED"
    )

def is_green(pr):
    required = [c for c in pr["statusCheckRollup"] if c.get("isRequired", False)]
    if not required:
        return True
    return all(c.get("conclusion") == "SUCCESS" for c in required)
```

Apply `--authors` filter if set.

Build:
- `merge_ready[]` — PRs ready to merge immediately
- `needs_fix[]` — PRs needing repair (conflicts/CI/reviews)
- `skipped_unknown[]` — PRs with UNKNOWN mergeable state

Apply blast radius caps:
- `needs_fix[]`: truncate to `--max-total-prs`
- `merge_ready[]`: truncate to `--max-total-merges`

### Phase 0 Output

```
Phase 0 Complete — Plan:
  READY TO MERGE:   <N> PRs (capped at <max_total_merges>)
  NEEDS FIX:        <M> PRs (capped at <max_total_prs>)
  UNKNOWN STATE:    <K> PRs (skipped)
  SKIPPED LEDGER:   <J> PRs (already processed, no change)
```

If `--dry-run`:
```
  → Print full plan (PR titles, repos, reasons)
  → Print re-run block:
      "Dry run complete. No phases executed.

      Re-run command:
        /pr-queue-pipeline --run-id <run_id> [original-args]

      Would write:
        ~/.claude/pr-queue/runs/<run_id>/ledger.json
        ~/.claude/pr-queue/runs/<run_id>/inventory.json
        ~/.claude/pr-queue/<date>/report_<run_id>.md
        ~/.claude/pr-queue/<date>/pipeline_<run_id>.json"
  → Emit ModelSkillResult(status=nothing_to_do, phases={scan: {...}})
  → EXIT
```

If both lists are empty (nothing to merge or fix):
```
  → Print: "Nothing to do — all PRs are merge-ready, UNKNOWN, or already done."
  → Emit ModelSkillResult(status=nothing_to_do)
  → EXIT
```

### Phase 0 Ledger and Inventory Write

After Phase 0 scan completes (and before any sub-skill dispatch):

1. **Write ledger** to `~/.claude/pr-queue/runs/<run_id>/ledger.json`:
   ```json
   {
     "run_id": "<run_id>",
     "started_at": "<ISO timestamp>",
     "phase_completed": ["scan"],
     "stop_reason": null,
     "inventory_path": "~/.claude/pr-queue/runs/<run_id>/inventory.json"
   }
   ```

2. **Write inventory** to `~/.claude/pr-queue/runs/<run_id>/inventory.json`:
   ```json
   {
     "run_id": "<run_id>",
     "generated_at": "<ISO timestamp>",
     "merge_ready": [...],
     "needs_fix": [...]
   }
   ```

**CRITICAL**: inventory.json MUST be written before fix-prs, merge-sweep, or review-all-prs is
invoked. Sub-skills receive `--inventory ~/.claude/pr-queue/runs/<run_id>/inventory.json`.

After each phase completes, append the phase name to `phase_completed` in the ledger. Phase names:
`scan` | `review` | `fix` | `merge` | `report`

**phase_completed never regresses** — only append, never remove or reorder.

### Claims Lifecycle

Before processing each PR, create a claim file at:
`~/.claude/pr-queue/claims/<run_id>/<repo_slug>-<pr_number>.json`

On terminal run completion (`completed`, `gate_rejected`, `nothing_to_do`, `error`):
Remove all claim files under `~/.claude/pr-queue/claims/<run_id>/`.

### stop_reason

Set `stop_reason` in the ledger when the pipeline reaches a terminal state:
- `completed` — all eligible phases ran, all PRs processed
- `partial_completed` — pipeline stopped after processing some (not all) eligible PRs
- `gate_rejected` — Phase 3 gate rejected by human
- `nothing_to_do` — Phase 0 found no work
- `error` — unrecoverable error

---

## Phase 1: Review (review-all-prs)

**INVARIANT**: Phase 1 must complete before Phase 2 begins. Never run review and fix concurrently.

Skip entirely if `--skip-review` is set. Log: "Phase 1 skipped (--skip-review)."

```
Invoke: Skill(skill="review-all-prs", args={
  repos: <scope>,
  max_total_prs: <max_total_prs>,
  max_parallel_prs: <max_parallel_prs>,
  max_parallel_repos: <max_parallel_repos>,
  clean_runs: <clean_runs>,
  max_review_minutes: <max_review_minutes>,
  skip_clean: true,    # Pipeline scans merge-ready PRs separately in Phase 0
  authors: <authors>
})
```

Wait for review-all-prs to complete. Capture result:
- `review_result.prs_reviewed` — total PRs reviewed
- `review_result.prs_fixed_and_pushed` — PRs that had commits pushed
- `review_result.status` — for ModelSkillResult phases

If review-all-prs returns `status: error`:
- Log warning: "Phase 1 review-all-prs returned error: <status>"
- Continue to Phase 1 re-scan (Phase 0 scan results remain valid)

### Phase 1 Re-Scan

After Phase 1 completes (whether success, partial, or error), **re-run the Phase 0 scan** to
pick up PRs that became merge-ready as a result of review commits:

```bash
# Re-run Phase 0 scan for all repos in scope
# Rebuild merge_ready[] and needs_fix[] with fresh data
# PRs that got review commits pushed may now be clean/mergeable
```

Update `merge_ready[]` and `needs_fix[]` with fresh data before Phase 2.

Log: "Phase 1 re-scan complete: <N> merge-ready (was <N_before>), <M> needs fix (was <M_before>)"

---

## Phase 2: Fix Phase (Sequential)

**INVARIANT**: Phase 2 must complete before Phase 3 begins. Never run fix and merge concurrently.

Skip if `--skip-fix` is set.

```
Invoke: Skill(skill="fix-prs", args={
  repos: <scope>,
  max_total_prs: <max_total_prs>,
  max_parallel_prs: <max_parallel_prs>,
  allow_force_push: <allow_force_push>,
  authors: <authors>
})
```

Wait for fix-prs to complete. Capture result:
- `fix_result.prs_fixed` — how many PRs were repaired
- `fix_result.status` — for ModelSkillResult phases

If fix-prs returns `status: error`:
- Log warning: "Phase 2 fix-prs returned error: <status>"
- Continue to Phase 3 with post-Phase-1 `merge_ready[]` list

---

## Phase 3: Gate + Merge (First Pass)

**Re-query PR state** after Phases 1+2 to pick up newly fixed or reviewed PRs:

```bash
# Re-run Phase 0 scan for all repos in scope
# Rebuild merge_ready[] with fresh data
# PRs fixed in Phase 2 or reviewed in Phase 1 that are now merge-ready appear here
```

Post single HIGH_RISK Slack gate using `slack-gate`:

```
Skill(skill="slack-gate", args={
  gate_id: sha256("<run_id>:pipeline-phase3")[:12],
  risk: "HIGH_RISK",
  message: """
PR Queue Pipeline — run <run_id>
Scope: <repos> | Authors: <authors or "all">

READY TO MERGE (<N> PRs):
<for each merge_ready PR:>
  • <repo>#<pr_number> — <title> (<check_count> ✓, <review_status>) SHA: <sha8>

<if review_result.prs_fixed_and_pushed > 0 (and not --skip-review):>
REVIEWED THIS RUN (Phase 1 applied local-review fixes):
<for each PR with fixed_and_pushed result:>
  • <repo>#<pr_number> — <local_review_iterations> iterations, fix pushed

<if phase2 prs_fixed > 0:>
REPAIRED THIS RUN (Phase 4 sweep picks these up if CI settles):
<for each fixed PR:>
  • <repo>#<pr_number> — <repair_summary>

Commands:
  approve all                    — merge all <N> ready PRs
  approve except <repo>#<pr>     — merge all except listed
  skip <repo>#<pr>               — exclude specific PR, merge rest
  reject                         — cancel merge phase

This is HIGH_RISK — silence will NOT auto-advance.
  """
})
```

Store: `gate_token = "<slack_message_ts>:<run_id>"`

On gate rejection (`explicit_reject` or `gate_rejected`):
```
→ Record gate_token in result
→ Write partial report (Phase 5)
→ Emit ModelSkillResult(status=gate_rejected)
→ EXIT
```

On approval, parse approved candidates (support `approve except`, `skip`).

Invoke merge-sweep in bypass mode:

```
Invoke: Skill(skill="merge-sweep", args={
  repos: <scope>,
  no_gate: true,
  gate_token: <gate_token>,
  max_total_merges: <max_total_merges>,
  max_parallel_prs: <max_parallel_prs>,
  merge_method: <merge_method>,
  authors: <authors>
})
```

Wait for merge-sweep to complete. Capture `merge_phase3_result`.

---

## Phase 4: Conditional Second Merge Pass

**Condition to run Phase 4** (ALL must be true):
1. Phase 2 `prs_fixed > 0` (fix-prs repaired at least one PR)
2. At least one of those repaired PRs is now `merge_ready` after Phase 3

Check condition:
```python
newly_ready = [pr for pr in phase2_fixed_prs if is_merge_ready(re_query(pr))]
run_phase4 = len(newly_ready) > 0
```

If condition is not met:
- Skip Phase 4 silently
- Log: "Phase 4 skipped — no newly-fixed PRs are merge-ready"

If condition is met:
```
Invoke: Skill(skill="merge-sweep", args={
  repos: <scope>,
  no_gate: true,
  gate_token: <gate_token>,  # Reuse Phase 3 gate_token
  max_total_merges: <remaining_merge_budget>,  # max_total_merges - phase3_merged
  max_parallel_prs: <max_parallel_prs>,
  merge_method: <merge_method>
})
```

`remaining_merge_budget = max_total_merges - merge_phase3_result.merged`

If remaining_merge_budget <= 0: skip Phase 4 (global cap reached).

Wait for merge-sweep to complete. Capture `merge_phase4_result`.

---

## Phase 5: Report

Build org queue report and ModelSkillResult.

### Report File

Write to `~/.claude/pr-queue/<date>/report_<run_id>.md`:

```markdown
# PR Queue Pipeline Report — <run_id>
Date: <date> | v1 | Scope: <repos> | Authors: <authors>

## Summary
- Total PRs merged: <total_merged>
- Total PRs reviewed: <total_reviewed>
- Total PRs fixed: <total_fixed>
- Gate token: <gate_token>
- Duration: <elapsed>

## Merged (<N> PRs)
<for each merged PR:>
- <repo>#<pr_number> — <title> | <merge_method> | SHA: <sha8>

## Reviewed This Run (<N> PRs — Phase 1)
<for each PR reviewed in Phase 1:>
- <repo>#<pr_number> — <title> | <local_review_iterations> iterations | <result>

## Fixed This Run (<N> PRs — Phase 2)
<for each fix-prs fixed PR:>
- <repo>#<pr_number> — <title> | <phases_fixed>

## Still Blocked (<N> PRs)
<for each PR still not merge-ready:>
- <repo>#<pr_number> — <title> | reason: <reason>

## Needs Human Review (<N> PRs)
<for each needs_human PR:>
- <repo>#<pr_number> — retry_count: <N>, no progress

## Blocked External (<N> PRs)
<for each blocked_external PR:>
- <repo>#<pr_number> — blocked_check: <check_name>
```

If `--slack-report`:
- Post summary to Slack: "PR Queue Pipeline run <run_id> complete: <N> merged, <R> reviewed, <M> fixed, <K> still blocked"

### ModelSkillResult

```json
{
  "skill": "pr-queue-pipeline",
  "version": "0.2.0",
  "status": "<status>",
  "run_id": "<run_id>",
  "gate_token": "<gate_token>",
  "phases": {
    "scan": {
      "repos_scanned": <N>,
      "merge_ready": <N>,
      "needs_fix": <N>
    },
    "review_all_prs": {
      "status": "<review_result.status or 'skipped'>",
      "prs_reviewed": <review_result.prs_reviewed or 0>,
      "prs_fixed_and_pushed": <review_result.prs_fixed_and_pushed or 0>,
      "skipped": <bool>
    },
    "fix_prs": {
      "status": "<fix_result.status or 'skipped'>",
      "prs_fixed": <fix_result.prs_fixed or 0>,
      "skipped": <bool based on --skip-fix>
    },
    "merge_sweep_phase3": {
      "status": "<merge_phase3_result.status>",
      "merged": <merge_phase3_result.merged>
    },
    "merge_sweep_phase4": {
      "status": "<merge_phase4_result.status or 'skipped'>",
      "merged": <merge_phase4_result.merged or 0>
    }
  },
  "total_prs_merged": <phase3_merged + phase4_merged>,
  "total_prs_reviewed": <review_result.prs_reviewed or 0>,
  "total_prs_fixed": <fix_result.prs_fixed>,
  "total_prs_still_blocked": <still_blocked_count>,
  "total_prs_needs_human": <needs_human_count>,
  "total_prs_blocked_external": <blocked_external_count>,
  "report_path": "~/.claude/pr-queue/<date>/report_<run_id>.md"
}
```

### Status Selection

```
nothing_to_do   — Phase 0 found no merge-ready or fixable PRs
gate_rejected   — Phase 3 gate was rejected
error           — Phase 0 scan failed or Phase 3 merge-sweep failed
complete        — At least one PR merged and no errors
partial         — Some phases completed, some had failures (Phase 1, 2, or 4 errors)
```

Print final summary:

```
PR Queue Pipeline Complete — run <run_id>
  Merged:           <total_merged> PRs
  Reviewed:         <total_reviewed> PRs
  Fixed:            <total_fixed> PRs
  Still blocked:    <still_blocked> PRs
  Needs human:      <needs_human> PRs
  Blocked external: <blocked_external> PRs
  Status:           <status>
  Gate:             <gate_token>
  Report:           ~/.claude/pr-queue/<date>/report_<run_id>.md
```

---

## Error Handling

| Situation | Action |
|-----------|--------|
| Phase 0 scan fails entirely | Emit `status: error`, exit |
| Phase 1 review-all-prs returns error | Log warning, continue to Phase 1 re-scan + Phase 2 |
| Phase 2 fix-prs returns error | Log warning, continue to Phase 3 |
| Phase 3 gate rejected | Emit `status: gate_rejected`, write report, exit |
| Phase 3 merge-sweep fails | Emit `status: error`, write partial report, exit |
| Phase 4 condition not met | Skip Phase 4 silently |
| Phase 4 merge-sweep fails | Emit `status: partial` (Phase 3 succeeded) |
| Report write fails | Log warning; return result (non-blocking) |

---

## Sequencing Invariant (Critical)

The orchestrator MUST wait for each phase to complete before starting the next:

```
Phase 0 complete
  ↓ (wait)
Phase 1 complete (or skipped via --skip-review)
  ↓ (wait)
Phase 1 re-scan complete
  ↓ (wait)
Phase 2 complete (or skipped via --skip-fix)
  ↓ (wait)
Phase 3 complete
  ↓ (wait)
Phase 4 complete (or skipped)
  ↓ (wait)
Phase 5 complete
```

Never dispatch review, fix, and merge agents at the same time. Each phase must complete before
the next begins.
