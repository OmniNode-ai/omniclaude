# Merge Sweep Orchestration

You are the merge-sweep orchestrator. This prompt defines the complete execution logic.

## Initialization

When `/merge-sweep [args]` is invoked:

1. **Announce**: "I'm using the merge-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--dry-run` — default: false (zero filesystem writes including claims)
   - `--merge-method <method>` — default: squash
   - `--require-approval <bool>` — default: true
   - `--require-up-to-date <policy>` — default: repo
   - `--max-total-merges <n>` — default: 10
   - `--max-parallel-prs <n>` — default: 5
   - `--max-parallel-repos <n>` — default: 3
   - `--max-parallel-polish <n>` — default: 2
   - `--skip-polish` — default: false; skip the pr-polish phase entirely
   - `--polish-clean-runs <n>` — default: 2; consecutive clean local-review passes required during polish
   - `--authors <list>` — default: all
   - `--since <date>` — default: none (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
   - `--label <labels>` — default: all (comma-separated for any-match)
   - `--run-id <id>` — default: generate new; provided by pr-queue-pipeline for claim ownership

3. **Generate or restore run_id**:
   - If `--run-id` provided: use it (resume mode — no ledger for merge-sweep, but claim registry uses it)
   - Otherwise: generate `<YYYYMMDD-HHMMSS>-<random6>` (e.g., `20260223-143012-a3f`)

3a. **Startup resume — clean stale own claims**:

```python
from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry

registry = ClaimRegistry()
deleted = registry.cleanup_stale_own_claims(run_id, dry_run=dry_run)
if deleted:
    print(f"[merge-sweep] Cleaned up {len(deleted)} stale claim(s) from prior run: {deleted}")
```

4. **Record filters** for `ModelSkillResult`:
   ```python
   filters = {
       "since": since_str or None,
       "labels": label_list or [],
       "authors": author_list or [],
       "repos": repo_list or [],
   }
   ```

---

## Step 1: Pre-Flight Validation

**CRITICAL**: Before any scanning or I/O, validate arguments:

```
IF --since is set:
  → Parse date using parse_since() (see below)
  → IF parse fails: print "ERROR: Cannot parse --since date: <value>. Use YYYY-MM-DD or ISO 8601."
  → Emit ModelSkillResult(status=error, error="--since parse error: <value>")
  → EXIT immediately

IF --label is set:
  → Split by comma: filter_labels = [l.strip() for l in label_arg.split(",")]
```

### Date Parsing Helper

```python
from datetime import datetime, timezone

def parse_since(since_str: str) -> datetime:
    """Parse ISO 8601 date or datetime string."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(since_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse --since date: {since_str!r}. Use YYYY-MM-DD or ISO 8601.")
```

---

## Step 2: Determine Repo Scope

If `--repos` is provided, use that list. Otherwise, use the canonical omni_home repo list:

Known omni_home repos (update as workspace grows):
- `OmniNode-ai/omniclaude`
- `OmniNode-ai/omnibase_core`
- `OmniNode-ai/omniintelligence`
- `OmniNode-ai/omniarchon`
- `OmniNode-ai/omnidash`

If a repo manifest exists at `~/Code/omni_home/repos.yaml`, read from it instead of the
hardcoded list above.

---

## Step 3: Scan Phase (Parallel, Tier-Aware)

Scan up to `--max-parallel-repos` repos concurrently. The scan method depends on the
current ONEX tier (see `@_lib/tier-routing/helpers.md`):

```python
tier = detect_onex_tier()
```

### FULL_ONEX Path

Use `node_git_effect.pr_list()` for typed, structured output:

```python
from omniclaude.nodes.node_git_effect.models import (
    GitOperation, ModelGitRequest, ModelPRListFilters,
)

request = ModelGitRequest(
    operation=GitOperation.PR_LIST,
    repo=f"{GITHUB_ORG}/{repo}",
    json_fields=[
        "number", "title", "mergeable", "statusCheckRollup",
        "reviewDecision", "headRefName", "baseRefName",
        "baseRepository", "headRepository", "headRefOid",
        "author", "labels", "updatedAt", "isDraft",
    ],
    list_filters=ModelPRListFilters(state="open", limit=100),
)
result = await handler.pr_list(request)
```

### STANDALONE / EVENT_BUS Path

Use `_bin/pr-scan.sh` for structured JSON output via `gh` CLI:

```bash
${CLAUDE_PLUGIN_ROOT}/_bin/pr-scan.sh \
  --repo <repo> \
  --state open \
  --limit 100 \
  ${AUTHOR:+--author $AUTHOR} \
  ${LABEL:+--label $LABEL} \
  ${SINCE:+--since $SINCE}
```

The script wraps `gh pr list` with consistent field selection and optional `--since`
date filtering (applied via `jq` post-filter). Output format is identical to the raw
`gh pr list` JSON array.

### Fallback (Legacy)

If neither `node_git_effect` nor `_bin/pr-scan.sh` is available, fall back to raw `gh`:

```bash
gh pr list \
  --repo <repo> \
  --state open \
  --json number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,baseRepository,headRepository,headRefOid,author,labels,updatedAt,isDraft \
  --limit 100
```

**IMPORTANT**: `labels`, `updatedAt`, and `isDraft` are required JSON fields.

For each PR returned, apply classification:

### PR Classification Logic

```python
def is_green(pr):
    """All REQUIRED checks have conclusion SUCCESS."""
    required = [c for c in pr["statusCheckRollup"] if c.get("isRequired", False)]
    if not required:
        return True  # no required checks = green
    return all(c.get("conclusion") == "SUCCESS" for c in required)

def is_merge_ready(pr, require_approval=True):
    """PR is safe to merge immediately."""
    if pr["isDraft"]:
        return False
    if pr["mergeable"] != "MERGEABLE":
        return False
    if not is_green(pr):
        return False
    if require_approval:
        return pr.get("reviewDecision") in ("APPROVED", None)
    return True

def needs_polish(pr, require_approval=True):
    """PR has fixable blocking issues: CI failures, conflicts, or changes requested."""
    if pr["isDraft"]:
        return False  # draft PRs are intentionally incomplete
    if pr["mergeable"] == "UNKNOWN":
        return False  # can't determine state — skip
    if is_merge_ready(pr, require_approval=require_approval):
        return False  # already ready — goes to auto-merge track
    # Fixable if: conflicting (resolvable), CI failing (fixable), or changes requested (addressable)
    if pr["mergeable"] == "CONFLICTING":
        return True
    if not is_green(pr):
        return True
    if require_approval and pr.get("reviewDecision") == "CHANGES_REQUESTED":
        return True
    return False  # other cases (e.g., REVIEW_REQUIRED — needs human, not automation)

def pr_state_unknown(pr):
    return pr["mergeable"] == "UNKNOWN"

def passes_since_filter(pr, since):
    """Return True if PR was updated at or after the since datetime."""
    if since is None:
        return True
    updated_at = pr.get("updatedAt", "")
    if not updated_at:
        return True  # unknown: include conservatively
    pr_updated = datetime.fromisoformat(updated_at.rstrip("Z")).replace(tzinfo=timezone.utc)
    return pr_updated >= since

def passes_label_filter(pr, filter_labels):
    """Return True if PR has any of the filter labels (or filter is empty)."""
    if not filter_labels:
        return True
    pr_labels = {label["name"] for label in pr.get("labels", [])}
    return bool(pr_labels & set(filter_labels))
```

Classification results:
- `is_merge_ready()` AND passes filters → add to `candidates_pre_claim[]` (Track A)
- `needs_polish()` AND passes filters → add to `polish_queue_pre_claim[]` (Track B)
- `pr_state_unknown()` → add to `skipped_unknown[]` with warning
- Draft PRs → ignore silently
- Otherwise (e.g., `REVIEW_REQUIRED`) → ignore silently

### Claim Registry Check (after filter classification)

For each PR in `candidates_pre_claim[]` and `polish_queue_pre_claim[]`, check the global claim registry:

```python
from plugins.onex.hooks.lib.pr_claim_registry import (
    ClaimRegistry, canonical_pr_key
)

registry = ClaimRegistry()
candidates = []
polish_queue = []
hard_failed_claims = []

for pr in candidates_pre_claim + polish_queue_pre_claim:
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    pr_key = canonical_pr_key(org=base_owner, repo=base_repo_name, number=pr["number"])

    claim = registry.get_claim(pr_key)
    if claim and registry.has_active_claim(pr_key):
        hard_failed_claims.append({
            "pr_key": pr_key,
            "claimed_by_run": claim.get("claimed_by_run"),
            "action": claim.get("action"),
        })
        print(
            f"[merge-sweep] HARD FAIL: {pr_key} has active claim "
            f"(run: {claim.get('claimed_by_run')}, action: {claim.get('action')}). "
            f"Excluding from candidates.",
            flush=True,
        )
    elif pr in candidates_pre_claim:
        candidates.append(pr)
    else:
        polish_queue.append(pr)

if hard_failed_claims:
    print(
        f"[merge-sweep] {len(hard_failed_claims)} PR(s) excluded due to active claims: "
        + ", ".join(h["pr_key"] for h in hard_failed_claims)
    )
```

Apply `--authors` filter: if set, only include PRs where `pr["author"]["login"]` is in the authors list.
(Apply before claim check, as part of `passes_*_filter` calls above.)

Apply `--max-total-merges` cap: truncate `candidates[]` to the cap.
The polish queue is NOT capped (polishing is best-effort and additive).

---

## Step 4: Empty Check

```
IF candidates is empty AND polish_queue is empty (or --skip-polish):
  → Print: "No actionable PRs found across <N> repos."
  → If applicable, explain filters
  → If skipped_unknown is not empty: print warning about UNKNOWN state PRs
  → Emit ModelSkillResult(status=nothing_to_merge, filters=filters)
  → EXIT
```

---

## Step 5: Dry Run Check

```
IF --dry-run:
  → Print candidates table and polish queue table (see format below)
  → Print: "Dry run complete. No auto-merge enabled, no pr-polish dispatched."
  → Emit ModelSkillResult(status=nothing_to_merge, candidates_found=<N>, polished=0, auto_merge_set=0, skipped=0, failed=0, filters=filters)
  → EXIT
```

### Dry Run Output Format

```
MERGE-READY PRs — Track A: Enable GitHub auto-merge (<count>):
Filters: since=<since_date> | labels=<labels> | authors=<authors>

  OmniNode-ai/omniclaude
    #247  feat: auto-detect [OMN-2xxx]     5 checks ✓  APPROVED       SHA: cbca770e  updated: 2026-02-23
    #251  fix: validator skip              3 checks ✓  no review req  SHA: aab12340  updated: 2026-02-22

  OmniNode-ai/omnibase_core
    #88   fix: null guard in parser        2 checks ✓  APPROVED       SHA: ff3ab12c  updated: 2026-02-20

BLOCKING ISSUES — Track B: pr-polish queue (<count>):

  OmniNode-ai/omnidash
    #19   feat: dashboard redesign         CONFLICTING                SHA: d3f9a22b  updated: 2026-02-22
    #21   fix: chart rendering             CI FAILING (2 required)    SHA: ab12c340  updated: 2026-02-23

  OmniNode-ai/omniclaude
    #255  refactor: session handler        CHANGES_REQUESTED          SHA: 1a2b3c4d  updated: 2026-02-21

SKIPPED (UNKNOWN merge state — GitHub computing):
    OmniNode-ai/omnidash#20

Total: <N> ready to auto-merge, <M> need polishing, <K> skipped
```

---

## Step 6 — Phase A: Enable GitHub Auto-Merge (Parallel)

For each PR in `candidates[]`, acquire a claim and enable GitHub auto-merge.
Run up to `--max-parallel-prs` concurrently.

```python
from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry, canonical_pr_key

registry = ClaimRegistry()
auto_merge_results = []

for pr in candidates:
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    repo_full = f"{base_owner}/{base_repo_name}"
    pr_key = canonical_pr_key(org=base_owner, repo=base_repo_name, number=pr["number"])

    acquired = registry.acquire(pr_key, run_id=run_id, action="auto_merge_enable", dry_run=dry_run)
    if not acquired:
        auto_merge_results.append({
            "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
            "result": "failed", "error": "claim_race_condition"
        })
        continue

    try:
        # Enable GitHub auto-merge — merges automatically when all required checks pass
        result = run([
            "gh", "pr", "merge", str(pr["number"]),
            "--repo", repo_full,
            f"--{merge_method}",
            "--auto",
        ])
        if result.returncode == 0:
            auto_merge_results.append({
                "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                "result": "auto_merge_set", "head_sha": pr["headRefOid"][:8]
            })
            print(f"  ✓ auto-merge enabled: {repo_full}#{pr['number']} — {pr['title'][:60]}")
        else:
            auto_merge_results.append({
                "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                "result": "failed", "error": result.stderr.strip()
            })
            print(f"  ✗ failed to enable auto-merge: {repo_full}#{pr['number']} — {result.stderr.strip()}")
    finally:
        registry.release(pr_key, run_id=run_id, dry_run=dry_run)
```

---

## Step 7 — Phase B: Polish PRs with Blocking Issues (Parallel)

Skip this entire phase if `--skip-polish` is set or `polish_queue` is empty.

For each PR in `polish_queue[]`, dispatch a polymorphic agent that:
1. Creates a temporary worktree for the PR branch
2. Runs `pr-polish`
3. Checks if the PR is now merge-ready
4. If yes: enables GitHub auto-merge
5. Cleans up the worktree

Run up to `--max-parallel-polish` concurrently (default 2 — pr-polish is resource-intensive).

```python
polish_results = []

for pr in polish_queue:
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    repo_full = f"{base_owner}/{base_repo_name}"
    repo_name = base_repo_name  # short name, e.g. "omniclaude"
    branch = pr["headRefName"]
    pr_number = pr["number"]
    pr_key = canonical_pr_key(org=base_owner, repo=base_repo_name, number=pr_number)
    omni_home = os.environ.get("OMNI_HOME", str(Path.home() / "Code" / "omni_home"))
    worktree_base = os.environ.get("OMNI_WORKTREES", str(Path(omni_home).parent / "omni_worktrees"))
    worktree_path = f"{worktree_base}/merge-sweep-{run_id}/{repo_name}-pr-{pr_number}"

    acquired = registry.acquire(pr_key, run_id=run_id, action="polish", dry_run=dry_run)
    if not acquired:
        polish_results.append({
            "pr_key": pr_key, "repo": repo_full, "pr": pr_number,
            "result": "skipped", "skip_reason": "active_claim"
        })
        continue

    try:
        Task(
          subagent_type="onex:polymorphic-agent",
          description=f"Polish PR {repo_full}#{pr_number}",
          prompt=f"""Polish PR #{pr_number} in {repo_full} to resolve its blocking issues.

The PR has the following blocking state:
  Branch: {branch}
  Mergeable: {pr['mergeable']}
  CI: {'failing' if not is_green(pr) else 'passing'}
  Review: {pr.get('reviewDecision', 'none')}

Steps:

1. Fetch the branch and create a worktree:
   ```bash
   git -C {omni_home}/{repo_name} fetch origin {branch}
   git -C {omni_home}/{repo_name} worktree add \
     {worktree_path} {branch}
   cd {worktree_path}
   ```

2. Run pr-polish from inside the worktree:
   ```
   Skill(skill="onex:pr-polish", args="{pr_number} --required-clean-runs {polish_clean_runs}")
   ```
   pr-polish will resolve conflicts, fix CI failures and review comments, run local-review loop, and push.

3. After pr-polish completes, check if the PR is now merge-ready:
   ```bash
   gh pr view {pr_number} --repo {repo_full} --json mergeable,statusCheckRollup,reviewDecision
   ```
   Parse the result using is_merge_ready() logic (mergeable=MERGEABLE, all required CI green, reviewDecision in APPROVED/None).

4. If merge-ready: enable GitHub auto-merge:
   ```bash
   gh pr merge {pr_number} --repo {repo_full} --{merge_method} --auto
   ```

5. Clean up the worktree:
   ```bash
   git -C {omni_home}/{repo_name} worktree remove {worktree_path} --force
   ```

Return a JSON result:
{{
  "pr": {pr_number},
  "repo": "{repo_full}",
  "polish_status": "DONE | PARTIAL | BLOCKED",
  "auto_merge_set": true | false,
  "error": null | "<error message>"
}}"""
        )
    finally:
        registry.release(pr_key, run_id=run_id, dry_run=dry_run)
```

Wait for all polish agents to complete. Collect results into `polish_results[]`.

---

## Step 8: Collect Results

```python
auto_merge_set_count = sum(1 for r in auto_merge_results if r["result"] == "auto_merge_set")
auto_merge_failed_count = sum(1 for r in auto_merge_results if r["result"] == "failed")

polish_done_count = sum(1 for r in polish_results if r.get("polish_status") == "DONE")
polish_partial_count = sum(1 for r in polish_results if r.get("polish_status") == "PARTIAL")
polish_blocked_count = sum(1 for r in polish_results if r.get("polish_status") == "BLOCKED")
polish_auto_merged_count = sum(1 for r in polish_results if r.get("auto_merge_set"))

skipped_count = (
    len(skipped_unknown) + len(skipped_filtered)
    + sum(1 for r in polish_results if r.get("result") == "skipped")
    + len(hard_failed_claims)
)

total_auto_merge_set = auto_merge_set_count + polish_auto_merged_count
total_failed = auto_merge_failed_count + polish_blocked_count

if total_auto_merge_set > 0 and total_failed == 0:
    status = "queued"
elif total_auto_merge_set > 0 and total_failed > 0:
    status = "partial"
elif total_auto_merge_set == 0 and total_failed > 0:
    status = "error"
else:
    status = "nothing_to_merge"  # all candidates were skipped or blocked
```

---

## Step 9: Post Sweep Summary to Slack

Post a LOW_RISK informational summary. No polling — this is notification only.
Best-effort: if posting fails, log warning and continue.

```bash
source ~/.omnibase/.env 2>/dev/null || true
# If Slack credentials missing, skip notification (not a hard failure)
```

```python
summary_lines = [
    f"*[merge-sweep]* run {run_id} complete\n",
    f"Track A (auto-merge enabled):  {auto_merge_set_count} PRs queued | {auto_merge_failed_count} failed",
    f"Track B (pr-polish):           {polish_done_count} fixed → {polish_auto_merged_count} queued | "
    f"{polish_partial_count} partial | {polish_blocked_count} blocked",
]

if filters.get("since") or filters.get("labels") or filters.get("authors"):
    filter_parts = []
    if filters.get("since"):
        filter_parts.append(f"since={filters['since']}")
    if filters.get("labels"):
        filter_parts.append(f"labels={','.join(filters['labels'])}")
    if filters.get("authors"):
        filter_parts.append(f"authors={','.join(filters['authors'])}")
    summary_lines.append(f"Filters: {' | '.join(filter_parts)}")

queued_prs = [r for r in auto_merge_results + polish_results if r.get("result") == "auto_merge_set" or r.get("auto_merge_set")]
if queued_prs:
    summary_lines.append("\nAuto-merge enabled:")
    for r in queued_prs:
        origin = " (after polish)" if r.get("auto_merge_set") and r not in auto_merge_results else ""
        summary_lines.append(f"  • {r['repo']}#{r['pr']}{origin}")

blocked_prs = [r for r in polish_results if r.get("polish_status") == "BLOCKED"]
if blocked_prs:
    summary_lines.append("\nBlocked (manual intervention needed):")
    for r in blocked_prs:
        summary_lines.append(f"  • {r['repo']}#{r['pr']} — {r.get('error', 'polish blocked')}")

failed_auto = [r for r in auto_merge_results if r["result"] == "failed"]
if failed_auto:
    summary_lines.append("\nFailed to enable auto-merge:")
    for r in failed_auto:
        summary_lines.append(f"  • {r['repo']}#{r['pr']} — {r.get('error', 'unknown error')}")

summary_lines.append(f"\nStatus: {status} | Run: {run_id}")

summary_message = "\n".join(summary_lines)

try:
    post_to_slack(summary_message, channel=SLACK_CHANNEL_ID, bot_token=SLACK_BOT_TOKEN)
except Exception as e:
    print(f"WARNING: Failed to post summary to Slack: {e}", file=sys.stderr)
    # Do NOT fail the skill result — summary is best-effort
```

---

## Step 10: Emit ModelSkillResult

```json
{
  "skill": "merge-sweep",
  "status": "<status>",
  "run_id": "<run_id>",
  "filters": {
    "since": "<since_str or null>",
    "labels": ["<label1>"],
    "authors": ["<author1>"],
    "repos": ["<repo1>"]
  },
  "candidates_found": <N>,
  "polish_queue_found": <M>,
  "auto_merge_set": <count>,
  "polished": <polish_done_count>,
  "polish_partial": <polish_partial_count>,
  "polish_blocked": <polish_blocked_count>,
  "skipped": <count>,
  "failed": <count>,
  "details": [
    {
      "repo": "<repo>",
      "pr": <pr_number>,
      "head_sha": "<sha>",
      "track": "A | B",
      "result": "auto_merge_set | polished_and_queued | polished_partial | blocked | failed | skipped",
      "merge_method": "<method>",
      "skip_reason": null | "UNKNOWN_state" | "since_filter" | "label_filter" | "active_claim" | "draft"
    }
  ]
}
```

Write result to: `~/.claude/skill-results/<run_id>/merge-sweep.json`

Print summary:

```
Merge Sweep Complete — run <run_id>

  Track A (auto-merge enabled):  <auto_merge_set_count> queued | <auto_merge_failed_count> failed
  Track B (pr-polish):           <polish_done_count> fixed → <polish_auto_merged_count> queued
                                 <polish_partial_count> partial | <polish_blocked_count> blocked
  Skipped:                       <skipped_count> PRs

  Status: <status>
```

---

## Error Handling

| Situation | Action |
|-----------|--------|
| `--since` parse failure | Immediate error in Step 1, show format hint |
| `gh pr list` network failure for a repo | Log warning, skip repo, continue others |
| All repos fail to scan | Return `status: error` |
| `gh pr merge --auto` fails for a PR | Record `result: failed` in details, continue others |
| pr-polish BLOCKED (conflicts unresolvable) | Record `result: blocked`, skip auto-merge for that PR |
| pr-polish PARTIAL (max iterations hit) | Record `result: polished_partial`, skip auto-merge |
| Worktree creation fails | Record `result: failed`, release claim, continue others |
| Worktree cleanup fails | Log warning, do NOT fail the skill result |
| Slack summary post fails | Log warning only; do NOT fail skill result |
| Claim race condition | Record `result: failed, error: claim_race_condition` |

---

## Composability

This skill is designed to be called from `pr-queue-pipeline`:

```
# From pr-queue-pipeline Phase 3:
Skill(skill="onex:merge-sweep", args={
  repos: <scope>,
  max_total_merges: <cap>,
  max_parallel_prs: <cap>,
  max_parallel_polish: <cap>,
  merge_method: <method>,
  since: <date>,                  # optional date filter
  label: <label>,                 # optional label filter
  run_id: <pipeline_run_id>,      # claim registry ownership
  dry_run: <dry_run>,             # propagates to claim registry (zero writes)
  skip_polish: false              # set true to skip Track B in pipeline context if fix-prs already ran
})
```
