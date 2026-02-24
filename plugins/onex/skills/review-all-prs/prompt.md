# Review All PRs Orchestration

You are the review-all-prs orchestrator. This prompt defines the complete execution logic.

## Initialization

When `/review-all-prs [args]` is invoked:

1. **Announce**: "I'm using the review-all-prs skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--clean-runs <n>` — default: 2
   - `--skip-clean` — default: false
   - `--max-total-prs <n>` — default: 20
   - `--max-parallel-prs <n>` — default: 5
   - `--max-review-minutes <n>` — default: 30
   - `--skip-large-repos` — default: false
   - `--large-repo-file-threshold <n>` — default: 5000
   - `--cleanup-orphans` — default: false
   - `--orphan-age-hours <n>` — default: 4
   - `--max-parallel-repos <n>` — default: 3
   - `--authors <list>` — default: me (invoking user)
   - `--all-authors` — default: false (requires gate flags; see Scope Guard below)
   - `--gate-attestation <token>` — required with --all-authors; format: `<slack_ts>:<run_id>`
   - `--omn-2613-merged` — default: false (required with --all-authors unless --accept-duplicate-ticket-risk)
   - `--accept-duplicate-ticket-risk` — default: false (required with --all-authors when --omn-2613-merged absent)

3. **Generate run_id**: `<YYYYMMDD-HHMMSS>-<random6>` (e.g., `20260223-150812-c9f`)

4. **Print header**:
   ```
   Review All PRs v0 — run <run_id>
   Scope: <repos or "all"> | Authors: <authors or "all"> | Clean runs: <clean_runs>
   ```

---

## Scope Guard (Evaluated Immediately After Argument Parse)

**Default scope**: `authors = [me]` (the invoking user). This is the safe default.

**If `--all-authors` is set**:

**Step 1** — Verify `--gate-attestation` is present:
```
IF --gate-attestation is absent:
  → hard_error: "--all-authors requires --gate-attestation=<slack_ts>:<run_id>.
      Obtain a gate token from the Slack review-all-prs gate before running org-wide."
  → EXIT immediately
```

**Step 2** — Verify OMN-2613 flag:
```
IF neither --omn-2613-merged NOR --accept-duplicate-ticket-risk is set:
  → hard_error: "--all-authors requires either:
      --omn-2613-merged  (if OMN-2613 fingerprinted dedup is merged), or
      --accept-duplicate-ticket-risk  (explicit risk acceptance for duplicate tickets).
      See OMN-2613 for context."
  → EXIT immediately
```

**Step 3** — Set effective author scope to `all`:
```
IF both conditions pass:
  → effective_authors = ALL (no author filter applied)
  → Print: "Scope: all authors (gate-attested; run_id=<run_id>)"
```

**If `--all-authors` is NOT set**:
```
→ effective_authors = args.authors if --authors provided, else [me]
→ All-authors expansion is NOT possible without the full guard flag set
```

---

## Dry-Run Mode

When `--dry-run` is set:

1. **No claim files written** — `acquire_claim()` is skipped; no `~/.claude/pr-queue/claims/` writes
2. **No worktrees created** — `git worktree add` is NOT called
3. **No ledger writes** — `atomic_write()` raises `DryRunWriteError`; ledger is not updated
4. **No marker files** — `.onex_worktree.json` not written
5. **All output to stdout** — preview of what would be reviewed

The `--dry-run` flag propagates to all sub-calls using `atomic_write()` from
`_lib/pr-safety/helpers.md`. Caught `DryRunWriteError` exceptions are logged as
`[DRY RUN] skipped write: <path>` without aborting.

---

## Preflight Tripwire

Before dispatching any agent in Step 5, verify claim integrity for all PRs in `work_queue`:

```python
for pr in work_queue:
    pr_key = f"{pr['repo'].lower()}#{pr['number']}"
    cpath = claim_path(pr_key)
    wt_path = worktree_path_for(pr)

    if wt_path.exists() and not cpath.exists():
        hard_error(
            f"worktree exists for {pr_key} but no active claim held. "
            f"This indicates a claim-worktree ordering violation. "
            f"Manual cleanup required: git worktree remove --force {wt_path}"
        )
```

This tripwire fires if the orchestrator created a worktree without first acquiring a claim —
which should never happen but catches bugs in the worktree-creation flow.

---

## Startup: Orphan Sweeper (Always Runs)

Before any scan, run the orphan sweeper:

```bash
# Find all .onex_worktree.json markers under ~/.claude/worktrees/pr-queue/
find ~/.claude/worktrees/pr-queue/ -name ".onex_worktree.json" 2>/dev/null
```

For each marker found:
1. Read `created_at` from the JSON
2. Compute age = now - created_at
3. If age > `--orphan-age-hours` (in hours):
   - Read `path` (parent directory of marker)
   - Attempt: `git worktree remove --force <path>`
   - If succeeds: log "Removed orphaned worktree: <path>"
   - If fails: log "Warning: could not remove orphaned worktree: <path> (manual cleanup needed)"
   - Delete the marker file if worktree removal succeeded

If `--cleanup-orphans` is set:
```
→ Print orphan sweep summary
→ Emit ModelSkillResult(status=nothing_to_review, run_id=<run_id>) [sweeper-only mode]
→ EXIT
```

---

## Step 1: Determine Repo Scope

If `--repos` is provided, use that list. Otherwise use canonical omni_home repos:
- `OmniNode-ai/omniclaude`
- `OmniNode-ai/omnibase_core`
- `OmniNode-ai/omniintelligence`
- `OmniNode-ai/omniarchon`
- `OmniNode-ai/omnidash`

If `~/Code/omni_home/repos.yaml` exists, read from it instead.

**Large repo check** (if `--skip-large-repos` is set):

```bash
git -C ~/Code/<repo_name> ls-files | wc -l
```

Skip any repo where file count > `--large-repo-file-threshold`. Log: "Skipping <repo> — <N> files exceeds threshold of <threshold>."

---

## Step 2: Scan Phase (Parallel)

Scan up to `--max-parallel-repos` repos concurrently (default: 3). For each repo:

```bash
gh pr list \
  --repo <repo> \
  --state open \
  --json number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,headRefOid,author \
  --limit 100
```

If `gh pr list` fails for a repo: log warning, skip that repo, continue with others.
If ALL repos fail: emit `status: error`, exit.

Apply predicates to each PR:

```python
def is_merge_ready(pr):
    return (
        pr["mergeable"] == "MERGEABLE"
        and is_green(pr)
        and pr.get("reviewDecision") in ("APPROVED", None)
    )

def pr_state_unknown(pr):
    return pr["mergeable"] == "UNKNOWN"

def is_green(pr):
    required = [c for c in pr["statusCheckRollup"] if c.get("isRequired", False)]
    if not required:
        return True
    return all(c.get("conclusion") == "SUCCESS" for c in required)
```

### Classification per PR:
1. If `pr_state_unknown(pr)`: skip with warning ("UNKNOWN mergeable state, skipping")
2. If `--skip-clean` and `is_merge_ready(pr)`: skip (log "already merge-ready, skipped")
3. If `--authors` set and `pr["author"]["login"]` not in authors list: skip
4. **Ledger check**: load `~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json` if it exists
   - If entry exists AND `head_sha == pr["headRefOid"]` AND `last_result == "clean"`: skip (add to `prs_skipped_ledger`)
5. Otherwise: add to `work_queue[]`

Apply `--max-total-prs` cap: truncate `work_queue[]` to the cap.

### Step 2 Output:

```
Scan Complete:
  Repos scanned:     <N>
  PRs found:         <total open PRs>
  PRs to review:     <work_queue length>
  Skipped (ledger):  <prs_skipped_ledger>
  Skipped (unknown): <K>
  Skipped (clean):   <J>
```

---

## Step 3: Empty Check

```
IF work_queue is empty:
  → Print: "Nothing to review — all PRs are clean, unknown state, or skipped by ledger."
  → Emit ModelSkillResult(status=nothing_to_review)
  → EXIT
```

---

## Step 4: Create Worktrees (Before Dispatch)

For each PR in `work_queue[]`:

```python
# Worktree path
pr_key = f"{repo.lower()}#{pr_number}"
WORKTREE_PATH = f"~/.claude/worktrees/pr-queue/{run_id}/{repo_name}/{pr_number}"

# Step 4a: ACQUIRE CLAIM FIRST (before any worktree creation)
claim_result = acquire_claim(pr_key, run_id, "review")  # from _lib/pr-safety/helpers.md
if claim_result == "skip":
    # Another run holds this claim — skip this PR
    record(pr_key, result="skipped_claim")
    continue  # do NOT create worktree

# Step 4b: CREATE WORKTREE (only after claim acquired)
mkdir -p ~/.claude/worktrees/pr-queue/{run_id}/{repo_name}/
git -C ~/Code/{repo_name} worktree add {WORKTREE_PATH} {headRefName}
```

The `claim_path(pr_key)` file MUST exist (written by `acquire_claim()`) before
`git worktree add` is called. This ordering is invariant.

If worktree creation fails:
- Log: "Warning: could not create worktree for <repo>#<pr_number>: <error>"
- Record `result: failed` for this PR
- Remove from dispatch list; do NOT attempt to dispatch a review agent

After successful worktree creation, **immediately** write the marker:

```json
{
  "run_id": "<run_id>",
  "repo": "<repo>",
  "pr": <pr_number>,
  "branch": "<headRefName>",
  "base_ref": "<baseRefName>",
  "created_at": "<ISO timestamp>",
  "skill": "review-all-prs"
}
```

Write to: `<WORKTREE_PATH>/.onex_worktree.json`

**CRITICAL**: Write the marker BEFORE dispatching any agent. If the orchestrator crashes after
worktree creation but before marker write, the worktree becomes an orphan that can only be
cleaned manually. Marker-first guarantees the sweeper can find and remove it.

---

## Step 5: Dispatch Review Agents (Parallel)

Dispatch up to `--max-parallel-prs` agents concurrently. For each PR with a successfully created
worktree:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Review PR <repo>#<pr_number> — <title>",
  timeout_minutes=<max_review_minutes>,
  prompt="You are a PR review agent. Run local-review on PR #<pr_number> in repo <repo>.

    ## Context
    - PR title: <title>
    - Branch: <headRefName>
    - Base: <baseRefName>
    - Worktree path: <WORKTREE_PATH>

    ## Instructions

    Invoke local-review in the worktree:

    Skill(skill='local-review', args='--required-clean-runs <clean_runs>')

    Run this in the worktree directory: <WORKTREE_PATH>

    local-review will:
    1. Diff changes against the base branch
    2. Classify issues (Critical, Major, Minor, Nit)
    3. Fix Critical/Major/Minor issues and commit fixes
    4. Repeat until <clean_runs> consecutive clean passes or max-iterations reached

    After local-review completes:
    - If local-review made commits: run `git push origin <headRefName>` from <WORKTREE_PATH>
    - Post a PR comment summarizing what was reviewed and whether fixes were pushed:
      `gh pr comment <pr_number> --repo <repo> --body '<summary>'`

    ## Result

    Return JSON:
    {
      'repo': '<repo>',
      'pr': <pr_number>,
      'head_sha_before': '<original_headRefOid>',
      'head_sha_after': '<new_sha_if_pushed or original_sha_if_no_changes>',
      'result': 'clean | fixed_and_pushed | failed',
      'local_review_status': '<clean | max_iterations | error>',
      'local_review_iterations': <N>,
      'commits_pushed': <bool>,
      'pr_comment_posted': <bool>
    }"
)
```

On agent timeout (exceeds `--max-review-minutes`):
- Record `result: timed_out` for this PR
- Do NOT wait further; proceed to cleanup for that PR

Wait for all agents to complete (with timeout enforcement). Collect results.

---

## Step 6: Cleanup Worktrees

For each PR (whether the agent succeeded, failed, or timed out), in a `finally` block:

```python
# Step 6a: Remove worktree
git -C ~/Code/{repo_name} worktree remove --force {WORKTREE_PATH}

# Step 6b: Release claim (always, after worktree removal attempt)
release_claim(pr_key, run_id)  # from _lib/pr-safety/helpers.md
```

Release order: worktree removal first, then `release_claim()`. The claim is held until
the worktree is gone (or removal fails) to prevent another run acquiring the claim while
the old worktree still exists.

Record per PR:
- If worktree removal succeeds: `worktree_cleaned: true`
- If worktree removal fails: `worktree_cleaned: false`, add to `cleanup_failures[]`
  - Include path and repo/PR in the cleanup failure entry
- Claim is released regardless of worktree removal success/failure

Log any cleanup failures prominently:
```
WARNING: <N> worktrees could not be cleaned up automatically:
  <path1>
  <path2>
Run with --cleanup-orphans to retry cleanup.
```

---

## Step 7: Update Ledger

For each PR result, update the run ledger at
`~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json`:

```json
{
  "OmniNode-ai/omniclaude#247": {
    "head_sha": "<head_sha_after>",
    "last_result": "clean | fixed_and_pushed | failed | timed_out",
    "reviewed_at": "<ISO timestamp>",
    "local_review_iterations": <N>
  }
}
```

Write atomically (write to temp file, then rename).

---

## Step 8: Collect Results and Emit

Aggregate per-PR results:

```
prs_reviewed            = count of PRs dispatched (worktree created + agent ran)
prs_clean               = count where result == "clean"
prs_fixed_and_pushed    = count where result == "fixed_and_pushed"
prs_failed              = count where result == "failed"
prs_timed_out           = count where result == "timed_out"
prs_skipped_ledger      = count skipped by ledger check in Step 2
cleanup_failures        = list of {repo, pr, path} entries from Step 6
```

Status selection:
- `work_queue` was empty → `nothing_to_review`
- All repos failed to scan → `error`
- All reviewed PRs have `result: clean` OR `result: fixed_and_pushed` → `all_clean`
- Some PRs succeeded (clean or fixed_and_pushed), some failed or timed_out → `partial`
- Zero PRs succeeded (all failed or timed_out) → `partial` (work was attempted; still partial, not error)

Build and emit `ModelSkillResult`:

```json
{
  "skill": "review-all-prs",
  "version": "0.1.0",
  "status": "<status>",
  "run_id": "<run_id>",
  "prs_reviewed": <N>,
  "prs_clean": <K>,
  "prs_fixed_and_pushed": <J>,
  "prs_failed": <F>,
  "prs_timed_out": <T>,
  "prs_skipped_ledger": <S>,
  "cleanup_failures": [...],
  "details": [...]
}
```

Write to: `~/.claude/pr-queue/<date>/review-all-prs_<run_id>.json`

Print summary:

```
Review All PRs Complete — run <run_id>
  Repos scanned:        <N> repos
  PRs reviewed:         <prs_reviewed>
  Clean:                <prs_clean>
  Fixed and pushed:     <prs_fixed_and_pushed>
  Failed:               <prs_failed>
  Timed out:            <prs_timed_out>
  Skipped (ledger):     <prs_skipped_ledger>
  Cleanup failures:     <cleanup_failures count>
  Status:               <status>
```

If cleanup failures > 0:
```
  Manual cleanup required:
    Run: /review-all-prs --cleanup-orphans
    Or manually: git worktree remove --force <path>
```

---

## Error Handling

| Situation | Action |
|-----------|--------|
| `gh pr list` fails for one repo | Log warning, skip repo, continue |
| All repos fail to scan | Emit `status: error`, exit |
| Worktree creation fails | Record `failed`, skip agent dispatch, continue |
| Agent times out | Record `timed_out`, cleanup worktree, continue |
| `git push` fails in agent | Agent records `failed`, orchestrator records `failed` |
| Worktree cleanup fails | Record `cleanup_failed` in result; log path for manual cleanup |
| Ledger write fails | Log warning, continue (non-blocking) |
| Result file write fails | Log warning, return result anyway (non-blocking) |

---

## Sequencing

```
Orphan sweeper (always)
  ↓ (if --cleanup-orphans: exit here)
Step 1: Repo scope determination
  ↓
Step 2: Scan phase (parallel per repo)
  ↓
Step 3: Empty check
  ↓
Step 4: Create worktrees (sequential per PR, before dispatch)
  ↓
Step 5: Dispatch agents (parallel up to --max-parallel-prs)
  ↓ (wait for all agents, respecting --max-review-minutes per agent)
Step 6: Cleanup worktrees (per PR, after agent completes or times out)
  ↓
Step 7: Update ledger
  ↓
Step 8: Emit ModelSkillResult
```

Never dispatch agents before all worktrees for that batch are created and marked.
Never skip cleanup — always attempt worktree removal even on failure.
