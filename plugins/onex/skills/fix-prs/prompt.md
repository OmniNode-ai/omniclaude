# Fix PRs Orchestration

You are the fix-prs orchestrator. This prompt defines the complete execution logic.

## Initialization

When `/fix-prs [args]` is invoked:

1. **Announce**: "I'm using the fix-prs skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--category <cat>` — default: all (conflicts | ci | reviews | all)
   - `--max-total-prs <n>` — default: 20
   - `--max-parallel-prs <n>` — default: 5
   - `--max-parallel-repos <n>` — default: 3
   - `--max-fix-iterations <n>` — default: 3
   - `--authors <list>` — default: all
   - `--allow-force-push` — default: false
   - `--ignore-ledger` — default: false
   - `--run-id <id>` — default: generate new (resume mode if provided + ledger exists)
   - `--dry-run` — default: false (zero filesystem writes including claims and ledger)

3. **Generate or restore run_id**:
   - If `--run-id` provided AND ledger for that run_id exists: **resume mode** (log "Resuming run <run_id>")
   - Otherwise: generate `<YYYYMMDD-HHMMSS>-<random6>` (e.g., `20260223-150812-b7e4f9`)

3a. **Startup resume — clean stale own claims**:

```python
from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry

registry = ClaimRegistry()
deleted = registry.cleanup_stale_own_claims(run_id, dry_run=dry_run)
if deleted:
    print(f"[fix-prs] Cleaned up {len(deleted)} stale claim(s) from prior run: {deleted}")
```

This ensures any interrupted prior execution doesn't leave orphaned claims.

4. **Load ledger**: `~/.claude/pr-queue/<date>/run_<run_id>.json`
   - If `--ignore-ledger`: treat as empty ledger
   - If resuming (`--run-id` provided): derive `<date>` from the `run_id` prefix (parse `YYYYMMDD` from `run_id`); if that path doesn't exist, fall back to searching recent `~/.claude/pr-queue/` date dirs for `run_<run_id>.json`.
   - Otherwise: `<date>` = today's date in YYYY-MM-DD format

---

## Step 1: Determine Repo Scope

If `--repos` is provided, use that list. Otherwise use canonical omni_home repos:
- `OmniNode-ai/omniclaude`
- `OmniNode-ai/omnibase_core`
- `OmniNode-ai/omniintelligence`
- `OmniNode-ai/omniarchon`
- `OmniNode-ai/omnidash`

If `~/Code/omni_home/repos.yaml` exists, read from it instead.

---

## Step 2: Scan Phase (Parallel)

Scan up to `--max-parallel-repos` repos concurrently. For each repo:

```bash
gh pr list \
  --repo <repo> \
  --state open \
  --json number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,headRefOid,author \
  --limit 100
```

For each PR, apply predicates:

```python
def needs_conflict_work(pr):
    return pr["mergeable"] == "CONFLICTING"

def needs_ci_work(pr):
    required = [c for c in pr["statusCheckRollup"] if c.get("isRequired", False)]
    if not required:
        return False
    return any(c.get("conclusion") != "SUCCESS" for c in required)

def needs_review_work(pr):
    return pr.get("reviewDecision") == "CHANGES_REQUESTED"

def is_merge_ready(pr):
    return (
        pr["mergeable"] == "MERGEABLE"
        and not needs_ci_work(pr)
        and pr.get("reviewDecision") in ("APPROVED", None)
    )

def pr_state_unknown(pr):
    return pr["mergeable"] == "UNKNOWN"
```

### Classification Logic

For each PR:
1. If `is_merge_ready(pr)`: skip (merge-sweep handles these, log as `skipped_merge_ready`)
2. If `pr_state_unknown(pr)`: skip with warning, add to `skipped_unknown[]`
3. If at least one of `needs_conflict_work | needs_ci_work | needs_review_work` is true:
   - Apply `--authors` filter: skip if pr author not in authors list
   - Apply `--category` filter: only add work items matching requested categories
   - Check ledger: skip if `retry_count >= 3` AND `head_sha` unchanged AND `error_fingerprint` unchanged
   - Add to `work_queue[]`

Apply `--max-total-prs` cap: truncate `work_queue[]` to the cap.

---

## Step 3: Empty Check

```
IF work_queue is empty:
  → Print: "No PRs need repair across <N> repos."
  → Emit ModelSkillResult(status=nothing_to_fix)
  → EXIT
```

---

## Step 4: Dispatch Fix Agents (Parallel)

Before dispatching each PR agent, **acquire a claim** from the global registry.
Skip PRs where another active claim exists (from a different run). Release claims in
a `finally` block regardless of agent outcome.

```python
from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry, canonical_pr_key

registry = ClaimRegistry()

for pr in work_queue:
    pr_key = canonical_pr_key(org=pr["repo"].split("/")[0],
                               repo=pr["repo"].split("/")[1],
                               number=pr["number"])
    acquired = registry.acquire(pr_key, run_id=run_id, action="fix_pr", dry_run=dry_run)
    if not acquired:
        # Another active run holds this claim — skip (not a hard failure for fix-prs)
        record result: skipped, reason: claim_collision
        continue

    try:
        # dispatch agent (see Task() block below)
        ...
    finally:
        registry.release(pr_key, run_id=run_id, dry_run=dry_run)
```

Dispatch up to `--max-parallel-prs` agents concurrently. For each PR in work_queue:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Fix PR <repo>#<pr_number>",
  prompt="You are a PR repair agent. Fix PR #<pr_number> in repo <repo>.

    ## PR State
    - title: <title>
    - head_sha: <head_sha>
    - baseRefName: <baseRefName>  ← USE THIS for rebase, not hardcoded 'main'
    - needs_conflict_work: <bool>
    - needs_ci_work: <bool>
    - needs_review_work: <bool>
    - failing_checks: <list of check names and conclusions>

    ## Working Directory
    The repo is cloned at: ~/Code/<repo_name>/
    The PR branch is: <headRefName>

    ## Fix Steps (execute in order)

    ### Step A: Conflicts (if needs_conflict_work is true AND category includes conflicts)

    CRITICAL: Use pr.baseRefName for rebase, NEVER hardcode 'main'.

    ```bash
    cd ~/Code/<repo_name>
    git fetch origin <baseRefName>
    git checkout <headRefName>
    git rebase origin/<baseRefName>
    ```

    For each conflict:
    - Read conflicting files
    - Resolve intelligently (keep both changes where semantically valid)
    - Stage resolution: git add <file>
    - Continue: git rebase --continue

    On success:
    - git push --force-with-lease
    - Post PR comment: 'Resolved merge conflict via rebase onto <baseRefName> (fix-prs run <run_id>)'
    - Record result: conflict_resolved

    On rebase failure (cannot resolve):
    - git rebase --abort
    - Record result: conflict_unresolved
    - STOP (do not proceed to CI or review steps)

    ### Step B: Re-query after conflict resolution (if Step A resolved conflict)

    After pushing, wait up to 30s for GitHub to compute merge state:
    ```bash
    # Poll every 5s up to 6 times
    gh pr view <pr_number> --repo <repo> --json mergeable,statusCheckRollup,reviewDecision
    ```

    If is_merge_ready() now: record result=fixed, reason=resolved_by_rebase, STOP (skip C and D).

    ### Step C: CI Failures (if needs_ci_work is true AND category includes ci)

    First, inspect failing checks for external infra:

    External infra indicators (skip ci-failures for matching checks):
    - deploy, production, prod, staging, aws, gcp, azure, service-account, docker-push, publish, release, upload-to

    For each failing REQUIRED check:
    - If check name contains any indicator: mark blocked_external, skip
    - If all failing checks are blocked_external: record result=blocked_external, STOP (skip D)

    For non-external checks: invoke ci-failures sub-skill:
    Skill(skill='onex:ci-failures', args={max_fix_iterations: <max_fix_iterations>})

    Record CI fix result.

    ### Step D: Review Comments (if needs_review_work AND CI now green AND category includes reviews)

    Invoke pr-review-dev sub-skill:
    Skill(skill='onex:pr-review-dev')

    GUARDRAILS:
    - Never auto-dismiss reviews (do not use gh api to dismiss)
    - Never force-push unless --allow-force-push was passed
    - Always post a PR comment summarizing changes made

    If --allow-force-push: you may use git push --force-with-lease if needed after review fixes.
    Always post PR comment: 'Addressed review comments via fix-prs run <run_id>'

    ## Result

    Return JSON:
    {
      'repo': '<repo>',
      'pr': <pr_number>,
      'head_sha': '<sha>',
      'result': 'fixed | partial | failed | needs_human | blocked_external',
      'phases': {
        'conflicts': 'resolved | skipped | failed | not_needed',
        'ci': 'fixed | blocked_external | failed | skipped | not_needed',
        'reviews': 'addressed | skipped | failed | not_needed'
      },
      'blocked_check': '<check_name or null>',
      'new_head_sha': '<sha after any pushes>'
    }"
)
```

Wait for all agents to complete. Collect results.

---

## Step 5: Update Ledger

For each PR result, update `~/.claude/pr-queue/<date>/run_<run_id>.json`:

```json
{
  "OmniNode-ai/omniclaude#247": {
    "head_sha": "<new_head_sha or original head_sha>",
    "last_error_fingerprint": "SHA256(<phase>|<error_class>|<check_name>|<first_error_line>)",
    "last_result": "<result>",
    "retry_count": <previous_retry_count + 1>
  }
}
```

Write atomically (write to temp file, then rename).

---

## Step 6: Collect Results and Emit

Aggregate per-PR results:

```
prs_fixed = count where result == "fixed"
prs_partial = count where result == "partial"
prs_failed = count where result == "failed"
prs_needs_human = count where result == "needs_human"
prs_blocked_external = count where result == "blocked_external"
prs_skipped_ledger = count skipped due to ledger
```

Status selection:
- `work_queue` was empty → `nothing_to_fix`
- All processed PRs have `result: fixed` → `all_fixed`
- Some fixed, some not → `partial`
- Zero fixed, some failed/blocked → `partial` (there was work, some failed)
- Unrecoverable scan failure → `error`

Build and emit `ModelSkillResult`:

```json
{
  "skill": "fix-prs",
  "status": "<status>",
  "run_id": "<run_id>",
  "prs_scanned": <N>,
  "prs_processed": <M>,
  "prs_fixed": <K>,
  "prs_partial": <J>,
  "prs_failed": <F>,
  "prs_needs_human": <H>,
  "prs_blocked_external": <B>,
  "prs_skipped_ledger": <S>,
  "details": [...]
}
```

Write to: `~/.claude/pr-queue/<date>/fix-prs_<run_id>.json`

Print summary:

```
Fix PRs Complete — run <run_id>
  Scanned:          <N> PRs across <repos> repos
  Processed:        <M> PRs
  Fixed:            <K> PRs
  Partial:          <J> PRs
  Failed:           <F> PRs
  Needs human:      <H> PRs
  Blocked external: <B> PRs
  Status:           <status>
```

---

## Error Handling

| Situation | Action |
|-----------|--------|
| `gh pr list` fails for a repo | Log warning, skip repo, continue |
| All repos fail to scan | Emit `status: error` |
| Rebase conflict unresolvable | Record `failed`, `reason: conflict_unresolved`, continue |
| External CI check | Record `blocked_external`, continue (skip ci-failures) |
| ci-failures skill error | Record `partial` or `failed`, continue |
| pr-review-dev skill error | Record `partial`, continue |
| Force-push rejected by remote | Log error, record `failed`, continue |

---

## Composability

This skill is designed to be called from `pr-queue-pipeline` as Phase 2:

```
# From pr-queue-pipeline Phase 2:
Skill(skill="onex:fix-prs", args={
  repos: <scope>,
  max_total_prs: <cap>,
  max_parallel_prs: <cap>,
  allow_force_push: false,
  ignore_ledger: false,
  run_id: <pipeline_run_id>,   # for claim registry + ledger namespacing
  dry_run: <dry_run>           # propagates to claim registry (zero writes)
})
```

The parent pipeline provides its own `run_id` which is passed through for ledger namespacing
and claim registry ownership. `--dry-run` propagates to all claim registry writes (zero I/O).
After fix-prs completes, the pipeline re-queries PR state before posting the merge gate.
