# Merge Sweep Orchestration

You are the merge-sweep orchestrator. This prompt defines the complete execution logic.

**Execution mode: FULLY AUTONOMOUS.**
- Without `--dry-run`: execute Phase A and Phase B immediately after classification (no questions).
- `--dry-run` is the only preview mechanism.

## Initialization

When `/merge-sweep [args]` is invoked:

1. **Announce**: "I'm using the merge-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--dry-run` — default: false (zero filesystem writes including claims)
   - `--merge-method <method>` — default: squash
   - `--require-approval <bool>` — default: true
   - `--require-up-to-date <policy>` — default: repo
   - `--max-total-merges <n>` — default: 0 (unlimited; set positive to cap)
   - `--max-parallel-prs <n>` — default: 5
   - `--max-parallel-repos <n>` — default: 3
   - `--max-parallel-polish <n>` — default: 2
   - `--skip-polish` — default: false; skip the pr-polish phase entirely
   - `--polish-clean-runs <n>` — default: 2; consecutive clean local-review passes required during polish
   - `--authors <list>` — default: all
   - `--since <date>` — default: none (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
   - `--label <labels>` — default: all (comma-separated for any-match)
   - `--run-id <id>` — default: generate new; provided by parent pipeline for claim ownership

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

## QPM Auto-Classification (Inline)

QPM classification runs automatically as part of the classify step — no flag required.
After standard Track A/B classification, every non-draft PR is also scored for acceleration:

```python
from merge_planner.classifier import PRContext, classify_pr
from merge_planner.scorer import score_pr, PROMOTION_THRESHOLD
from merge_planner.models import EnumPRQueueClass

def qpm_classify_and_label(pr, repo_full, queue_depth=0):
    """Classify PR for acceleration and auto-label if promoted.

    Called inline during the classify step for every non-draft PR.
    Returns True if PR was labeled as accelerator.
    """
    ctx = PRContext(
        number=pr["number"],
        repo=repo_full,
        title=pr["title"],
        is_draft=pr.get("isDraft", False),
        ci_status="success" if is_green(pr) else "failure",
        review_state=pr.get("reviewDecision", "none").lower(),
        changed_files=[f["path"] for f in pr.get("files", [])],
        labels=[l["name"] for l in pr.get("labels", [])],
    )

    queue_class = classify_pr(ctx)
    if queue_class != EnumPRQueueClass.ACCELERATOR:
        return False

    score = score_pr(ctx, queue_class, queue_depth)
    if score.net_score < PROMOTION_THRESHOLD:
        return False

    # Auto-apply qpm-accelerate label
    run(["gh", "pr", "edit", str(pr["number"]),
         "--repo", repo_full, "--add-label", "qpm-accelerate"])
    return True
```

In Phase A, PRs with the `qpm-accelerate` label get priority enqueue via
`qpm-enqueue.sh --jump` instead of normal `gh pr merge --auto`. This is transparent —
no separate phase, no flag, no user action required.

---

## 1. Pre-Flight Validation

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

## 2. Determine Repo Scope

If `--repos` is provided, use that list. Otherwise, use the canonical omni_home repo list:

Known omni_home repos (update as workspace grows):
- `OmniNode-ai/omniclaude`
- `OmniNode-ai/omnibase_core`
- `OmniNode-ai/omniintelligence`
- `OmniNode-ai/omnidash`

If a repo manifest exists at `~/Code/omni_home/repos.yaml`, read from it instead of the
hardcoded list above.

---

## 3. Scan Phase (Parallel, Tier-Aware)

Scan up to `--max-parallel-repos` repos concurrently. The scan method depends on the
current ONEX tier (see `@_lib/tier-routing/helpers.md`):

```python
tier = detect_onex_tier()
```

**Initialize per-repo result tracking before scanning:**

```python
# repo_scan_results maps repo_full_name → list of PRs (empty list = zero open PRs)
#                                        or None = scan failed / never returned
# Initialize ALL configured repos to None so silent misses are detectable.
repo_scan_results: dict[str, list | None] = {repo: None for repo in repo_list}
```

This distinguishes three states:
- `None` (initial, never updated) — scan never returned (silent failure or dropped in fan-out)
- `[]` (empty list) — scanned successfully, confirmed zero open PRs
- `[...prs]` — scanned successfully, returned one or more PRs

On successful scan of a repo, set `repo_scan_results[repo] = prs` (even if `prs == []`).
On scan failure (exception, non-zero exit, empty/null output), set `repo_scan_results[repo]`
to a sentinel `scan_failed` marker (see post-scan coverage assertion below).

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
        "number", "title", "mergeable", "mergeStateStatus",
        "statusCheckRollup",
        "reviewDecision", "headRefName", "baseRefName",
        "baseRepository", "headRepository", "headRefOid",
        "author", "labels", "updatedAt", "isDraft",
        "autoMergeRequest",
    ],
    list_filters=ModelPRListFilters(state="open", limit=100),
)
result = await handler.pr_list(request)
repo_scan_results[repo] = result.prs  # always set — even if empty list
```

### STANDALONE / EVENT_BUS Path

Use `_bin/pr-scan.sh` for structured JSON output via `gh` CLI:

```bash
${CLAUDE_PLUGIN_ROOT}/_bin/pr-scan.sh \
  --repo <repo> \
  --state open \
  --limit 50 \
  ${AUTHOR:+--author $AUTHOR} \
  ${LABEL:+--label $LABEL} \
  ${SINCE:+--since $SINCE}
```

The script wraps `gh pr list` with consistent field selection and optional `--since`
date filtering (applied via `jq` post-filter). Output format is identical to the raw
`gh pr list` JSON array.

On success: `repo_scan_results[repo] = parsed_json_array` (always set, even if `[]`).
On non-zero exit or exception: log warning, do NOT update `repo_scan_results[repo]` (leaves `None`).

### Fallback (Legacy)

If neither `node_git_effect` nor `_bin/pr-scan.sh` is available, fall back to raw `gh`:

```bash
gh pr list \
  --repo <repo> \
  --state open \
  --json number,title,mergeable,mergeStateStatus,statusCheckRollup,reviewDecision,headRefName,baseRefName,baseRepository,headRepository,headRefOid,author,labels,updatedAt,isDraft,autoMergeRequest \
  --limit 50
```

**IMPORTANT**: `labels`, `updatedAt`, `isDraft`, and `mergeStateStatus` are required JSON fields.

On success: `repo_scan_results[repo] = parsed_json_array`.
On failure: leave `repo_scan_results[repo] = None`.

### Post-Scan Coverage Assertion

After ALL parallel scan tasks complete, assert that every configured repo has an entry:

```python
# Post-scan coverage assertion (OMN-4517)
repos_scanned = 0
repos_failed = 0
scan_failure_details = []

for repo, scan_result in repo_scan_results.items():
    if scan_result is None:
        # Repo never returned — silent miss detected
        repos_failed += 1
        scan_failure_details.append({
            "repo": repo,
            "result": "scan_failed",
            "error": "scan never returned (silent miss in parallel fan-out)",
        })
        print(
            f"WARNING: [merge-sweep] Repo scan did not return: {repo}. "
            f"This repo is excluded from this run. Check gh auth and network.",
            file=sys.stderr,
        )
    else:
        repos_scanned += 1

if repos_failed > 0:
    print(
        f"WARNING: [merge-sweep] {repos_failed} repo(s) failed to scan and will be "
        f"excluded: {[d['repo'] for d in scan_failure_details]}",
        file=sys.stderr,
    )
```

**Behavior**:
- Missing repos are logged as `WARNING` and recorded in `ModelSkillResult.details` with
  `result: scan_failed`.
- Scan failures do NOT abort the run — successfully scanned repos are still processed.
- The `repos_scanned` and `repos_failed` counters are included in `ModelSkillResult`.
- The Slack sweep summary includes a scan failure warning when `repos_failed > 0`.

### Stack Detection (Post-Scan, Pre-Classification)

After scanning all open PRs across repos, detect stacked PR chains before classification.
Stacked PRs where the root is blocked should not be independently polished — only the root
needs attention.

```python
def detect_stacked_chains(repo_scan_results):
    """Detect stacked PR chains by matching baseRefName to headRefName.

    Returns:
        stacked_blocked: set of PR numbers whose root PR is not merge-ready
        chain_warnings: list of warning strings for deep stacks
    """
    # Build headRefName -> PR mapping per repo
    stacked_blocked = set()
    chain_warnings = []

    for repo, prs in repo_scan_results.items():
        if not prs:
            continue

        head_to_pr = {}
        for pr in prs:
            head_to_pr[pr.get("headRefName", "")] = pr

        # Build dependency graph: PR B depends on PR A if B.baseRefName == A.headRefName
        depends_on = {}  # pr_number -> parent_pr_number
        for pr in prs:
            base = pr.get("baseRefName", "main")
            if base != "main" and base in head_to_pr:
                parent = head_to_pr[base]
                depends_on[pr["number"]] = parent["number"]

        # Find chains and their roots
        def find_root(pr_number, visited=None):
            if visited is None:
                visited = set()
            if pr_number in visited:
                return pr_number  # cycle detected
            visited.add(pr_number)
            parent = depends_on.get(pr_number)
            if parent is None:
                return pr_number
            return find_root(parent, visited)

        # Group chains
        chains = {}  # root -> [chain members in order]
        for pr in prs:
            if pr["number"] in depends_on:
                root = find_root(pr["number"])
                chains.setdefault(root, []).append(pr["number"])

        for root_number, members in chains.items():
            chain_depth = len(members) + 1  # +1 for root
            root_pr = next((p for p in prs if p["number"] == root_number), None)

            print(f"[merge-sweep] Stacked PR chain detected in {repo}: "
                  f"root=#{root_number} depth={chain_depth} "
                  f"members={[f'#{m}' for m in members]}")

            if chain_depth > 3:
                chain_warnings.append(
                    f"WARNING: Stack depth {chain_depth} in {repo} "
                    f"(root=#{root_number}) exceeds recommended max of 3. "
                    f"Consider collapsing."
                )

            # If root is not merge-ready, mark all downstream as STACKED_BLOCKED
            if root_pr and not is_merge_ready(root_pr):
                for member in members:
                    stacked_blocked.add((repo, member))

    return stacked_blocked, chain_warnings

stacked_blocked, chain_warnings = detect_stacked_chains(repo_scan_results)
for warning in chain_warnings:
    print(f"[merge-sweep] {warning}")
```

During classification below, PRs in `stacked_blocked` are skipped (not routed to Track B).
They are logged as `STACKED_BLOCKED` — only the root PR receives polish or merge attention.

For each PR returned from successfully scanned repos, apply classification:

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
    # Note: UNKNOWN mergeable PRs are caught by needs_branch_update() first (first-match-wins)
    if pr["mergeable"] == "UNKNOWN":
        return False  # should not reach here — needs_branch_update() handles UNKNOWN
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

def needs_branch_update(pr):
    """PR needs branch update before merge can proceed.
    Catches two cases:
    1. mergeable=MERGEABLE but mergeStateStatus is BEHIND/UNKNOWN (stale branch)
    2. mergeable=UNKNOWN (GitHub hasn't computed state — update forces recomputation)
    mergeStateStatus values: BEHIND, BLOCKED, CLEAN, DIRTY, DRAFT, HAS_HOOKS, UNKNOWN, UNSTABLE
    """
    if pr["isDraft"]:
        return False
    if pr["mergeable"] == "MERGEABLE":
        return pr.get("mergeStateStatus", "").upper() in ("BEHIND", "UNKNOWN")
    if pr["mergeable"] == "UNKNOWN":
        return True  # stale PR — update branch to force GitHub recomputation
    return False

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

### Track A-rebase: Auto-Rebase for CONFLICTING PRs (F10/OMN-6475)

Before routing a CONFLICTING PR to Track B (pr-polish), attempt a lightweight rebase
using `gh pr update-branch`. This resolves most DIRTY states without the heavyweight
pr-polish cycle.

```python
def attempt_rebase(pr, repo_full):
    """Attempt lightweight rebase for CONFLICTING PR.

    Returns:
        "MERGEABLE" if rebase succeeded and PR is now mergeable
        "CONFLICTING" if rebase failed or PR is still conflicting
    """
    if pr["mergeable"] != "CONFLICTING":
        return pr["mergeable"]

    print(f"[merge-sweep] Track A-rebase: attempting update-branch for #{pr['number']} in {repo_full}")
    result = run(f"gh pr update-branch {pr['number']} --repo {repo_full} 2>&1")

    if result.returncode != 0:
        print(f"[merge-sweep] Track A-rebase: update-branch failed for #{pr['number']} — routing to Track B")
        return "CONFLICTING"

    # Wait for GitHub to recalculate mergeable status
    import time
    time.sleep(30)

    # Re-check mergeable status
    new_mergeable = run(
        f"gh pr view {pr['number']} --repo {repo_full} --json mergeable --jq .mergeable"
    ).strip()

    if new_mergeable == "MERGEABLE":
        print(f"[merge-sweep] Track A-rebase: #{pr['number']} is now MERGEABLE after update-branch")
        return "MERGEABLE"
    else:
        print(f"[merge-sweep] Track A-rebase: #{pr['number']} still {new_mergeable} after update-branch — routing to Track B")
        return new_mergeable
```

Classification results (evaluated in order — first match wins):
- `(repo, pr["number"]) in stacked_blocked` → log as `STACKED_BLOCKED`, skip entirely (root PR will be processed independently; do not dispatch pr-polish for downstream PRs)
- `needs_branch_update()` AND passes filters → add to `branch_update_queue_pre_claim[]` (Track A-update; includes UNKNOWN mergeable PRs)
- `is_merge_ready()` AND passes filters → add to `candidates_pre_claim[]` (Track A)
- `is_conflicting_but_rebaseable()` AND passes filters → attempt `attempt_rebase(pr, repo_full)`: if result is MERGEABLE, reclassify to `candidates_pre_claim[]` (Track A); otherwise add to `polish_queue_pre_claim[]` (Track B)
- `needs_polish()` AND passes filters → add to `polish_queue_pre_claim[]` (Track B)
- Draft PRs → ignore silently
- Otherwise (e.g., `REVIEW_REQUIRED`) → ignore silently

Where `is_conflicting_but_rebaseable(pr)` is: `pr["mergeable"] == "CONFLICTING" and not pr["isDraft"]`.

**Note**: `needs_branch_update()` is checked BEFORE `is_merge_ready()`. A PR that is MERGEABLE
but BEHIND/UNKNOWN on `mergeStateStatus` needs its branch updated before auto-merge can
proceed. Arming auto-merge on such PRs creates a chicken-and-egg deadlock when strict branch
protection (`strict: true`) is enabled.

### QPM Auto-Label Pass (after classification, before claim check)

After Track A/B classification, run `qpm_classify_and_label()` on every non-draft PR
that landed in `candidates_pre_claim[]` or `branch_update_queue_pre_claim[]`.
This auto-applies the `qpm-accelerate` label to accelerator PRs so Phase A can
use `jump=true` enqueue. The label persists on the PR — subsequent sweeps see it
without re-classifying.

```python
accelerator_count = 0
for pr in candidates_pre_claim + branch_update_queue_pre_claim:
    repo_full = pr["baseRepository"]["nameWithOwner"]
    if qpm_classify_and_label(pr, repo_full, queue_depth=len(candidates_pre_claim)):
        accelerator_count += 1

if accelerator_count > 0:
    print(f"[merge-sweep] QPM: labeled {accelerator_count} accelerator PR(s) with qpm-accelerate")
```


### Auto-Merge Enrollment Detection (F41)

After classification, identify open non-draft PRs that should have auto-merge enabled but
do not. A PR needs auto-merge enrollment if:
- It is not a draft (`isDraft == false`)
- It has `autoMergeRequest: null` (auto-merge not enabled)
- It is not already in `candidates[]` or `branch_update_queue[]` (those get auto-merge armed in Phase A)
- It is not in `polish_queue[]` (those get auto-merge armed after polish succeeds)
- It passes all active filters (since, label, author)

```python
auto_merge_missing = []

for repo, prs in repo_scan_results.items():
    if not prs:
        continue
    for pr in prs:
        if pr.get("isDraft", False):
            continue
        if pr.get("autoMergeRequest") is not None:
            continue  # already enrolled
        # OMN-6468: Never touch PRs already in the merge queue.
        # Dequeue/re-enqueue doubles CI time (~10 min waste per event).
        if pr.get("mergeQueueEntry") is not None or pr.get("mergeStateStatus", "").upper() == "QUEUED":
            continue
        pr_number = pr["number"]
        # Skip PRs already handled by other tracks
        if pr in candidates_pre_claim or pr in branch_update_queue_pre_claim or pr in polish_queue_pre_claim:
            continue
        if not passes_since_filter(pr, since) or not passes_label_filter(pr, filter_labels):
            continue
        auto_merge_missing.append(pr)

if auto_merge_missing:
    print(f"[merge-sweep] F41: {len(auto_merge_missing)} PR(s) missing auto-merge enrollment")
```

In Phase A (Step 6), before processing `candidates[]`, arm auto-merge on PRs in the
`auto_merge_missing` bucket using the same logic (merge queue detection, claim registry,
`gh pr merge --auto` or `enqueue_to_merge_queue`). These PRs are processed with the same
parallelism limits as regular candidates.

---

### Branch Protection Drift Pre-Scan

After classification, detect PRs that are BLOCKED despite all visible checks passing.
This is a symptom of branch protection drift (required check names that no longer match
actual CI job names).

```python
def detect_branch_protection_drift(pr):
    """Flag PRs that are BLOCKED + all checks green as potential branch protection drift."""
    if pr["mergeable"] == "BLOCKED" and is_green(pr):
        return True
    return False

blocked_green_prs = [pr for pr in all_prs if detect_branch_protection_drift(pr)]


# Cache for merge queue detection per-repo (OMN-5463)
_merge_queue_cache: dict[str, bool] = {}

def has_merge_queue(repo_full: str) -> bool:
    """Detect whether a GitHub repo has a merge queue enabled on its default branch.

    Uses the GitHub API to check branch protection rules for the merge queue
    configuration. Results are cached per-repo for the duration of the sweep.

    Args:
        repo_full: Full repo name (e.g., "OmniNode-ai/omniclaude").

    Returns:
        True if merge queue is enabled, False otherwise.
    """
    if repo_full in _merge_queue_cache:
        return _merge_queue_cache[repo_full]

    result = run([
        "gh", "api", f"repos/{repo_full}/branches/main/protection",
        "--jq", ".required_pull_request_reviews.merge_queue // false",
    ], capture_output=True, text=True)

    # Also check via the merge queue GraphQL field as a fallback
    if result.returncode != 0 or result.stdout.strip() == "false":
        # Try GraphQL: mergeQueueConfig presence indicates merge queue
        gql_result = run([
            "gh", "api", "graphql", "-f", f'query=query {{ '
            f'repository(owner: "{repo_full.split("/")[0]}", name: "{repo_full.split("/")[1]}") {{ '
            f'mergeQueue(branch: "main") {{ id }} }} }}',
            "--jq", ".data.repository.mergeQueue.id",
        ], capture_output=True, text=True)
        has_queue = gql_result.returncode == 0 and bool(gql_result.stdout.strip())
    else:
        has_queue = True

    _merge_queue_cache[repo_full] = has_queue
    return has_queue
```

If `blocked_green_prs` is non-empty, emit a diagnostic warning:

```
WARNING: {len(blocked_green_prs)} PR(s) are BLOCKED with all checks green.
This is likely caused by branch protection required check names that no longer
match actual CI job names (BRANCH_PROTECTION_DRIFT).

Affected PRs:
  - {repo}#{number}: {title}

Run `/gap detect --repo {repo}` or `python3 omni_home/scripts/audit-branch-protection.py`
to diagnose and auto-fix.
```

These PRs are NOT added to Track B (pr-polish cannot fix branch protection drift).
They remain in the "otherwise ignore" bucket but with an explicit warning.

### Claim Registry Check (after filter classification)

For each PR in `candidates_pre_claim[]` and `polish_queue_pre_claim[]`, check the global claim registry:

```python
from plugins.onex.hooks.lib.pr_claim_registry import (
    ClaimRegistry, canonical_pr_key
)

registry = ClaimRegistry()
branch_update_queue = []
candidates = []
polish_queue = []
hard_failed_claims = []

for pr in branch_update_queue_pre_claim + candidates_pre_claim + polish_queue_pre_claim:
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
    elif pr in branch_update_queue_pre_claim:
        branch_update_queue.append(pr)
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

Apply `--max-total-merges` cap: if > 0, truncate `candidates[]` to the cap. If 0, no cap applied.
The polish queue is NOT capped (polishing is best-effort and additive).

---

## 4. Empty Check

```
IF candidates is empty AND branch_update_queue is empty AND thread_resolve_queue is empty AND polish_queue is empty AND auto_merge_missing is empty:
  → Print: "No actionable PRs found across <N> repos."
  → If applicable, explain filters
  → Emit ModelSkillResult(status=nothing_to_merge, filters=filters)
  → EXIT
```

---

## 5. Dry Run Check

```
IF --dry-run:
  → Print candidates table and polish queue table (see format below)
  → Print: "Dry run complete. No auto-merge enabled, no pr-polish dispatched."
  → Emit ModelSkillResult(status=nothing_to_merge, candidates_found=<N>, polished=0, auto_merge_set=0, skipped=0, failed=0, filters=filters)
  → EXIT
```

### Dry Run Output Format

```
STALE BRANCHES — Track A-update: Update branch before merge (<count>):
Filters: since=<since_date> | labels=<labels> | authors=<authors>

  OmniNode-ai/omniclaude
    #260  feat: new validator              BEHIND         5 checks ✓  APPROVED  SHA: e4f5a678  updated: 2026-03-06
    #263  fix: routing edge case           UNKNOWN        3 checks ✓  APPROVED  SHA: b1c2d3e4  updated: 2026-03-06

MERGE-READY PRs — Track A: Enable GitHub auto-merge (<count>):

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

Total: <N> stale (branch update needed, includes UNKNOWN), <M> ready to auto-merge, <P> need polishing
```

---

## CRITICAL: No Human Confirmation Gate

**DO NOT pause, ask the user, or present options between classification and execution.**

After classification + empty check + dry-run check, proceed IMMEDIATELY to Phase A
and Phase B without any intermediate confirmation.

- If `--dry-run` is set: print tables and EXIT. That IS the preview mechanism.
- If `--dry-run` is NOT set: execute Phase A and Phase B unconditionally. Do not ask
  "shall I proceed?", "would you like me to continue?", or present classification as options.
- Do not include any conditional or opt-out phrasing ("unless", "if you want",
  "let me know", "proceeding unless you object") between tables and Phase A.
- Track B (pr-polish) runs automatically unless `--skip-polish` is passed.
- Do not present Track A and Track B as separate choices. Both execute concurrently.
- After printing Track A/Track B tables in non-dry-run mode, do not print any question,
  invitation, or statement ending with a question mark. The next heading rendered must
  be the Phase A heading.

The v3.0.0 design intentionally removed all human gates. Absence of `--dry-run` = full autonomous execution.

---

## Merge Queue Policy (OMN-6488)

**CRITICAL**: Never dequeue a PR from the merge queue to re-enqueue it.
If a PR is already in the merge queue (`mergeQueueEntry` is non-null in the GraphQL
response), leave it alone. Dequeue/re-enqueue doubles CI time because both CI runs
must complete (the concurrency group uses `cancel-in-progress` only for merge_group
events, not for the original PR run).

If a PR in the merge queue has failing CI:
- Wait for the current run to complete
- If it fails, the merge queue will automatically dequeue it
- Then address the failure via Track B (pr-polish)

When classifying PRs, treat PRs with `mergeQueueEntry != null` as **IN_MERGE_QUEUE**
and skip them entirely from both Track A and Track B.

---

## Step 5b — Phase A-update: Proactive Branch Updates (Sequential)

**Before enabling auto-merge**, update branches that are BEHIND or UNKNOWN. PRs with stale
branches will deadlock in the merge queue when strict branch protection (`strict: true`) is
enabled -- auto-merge waits for the branch to be current, but does NOT trigger branch updates.

Process `branch_update_queue[]` sequentially (not parallel) to respect GitHub API rate limits
and avoid cascading staleness.

```python
# Uses check_merge_state() and update_pr_branch() from @_lib/pr-safety/helpers.md
from plugins.onex.skills._lib.pr_safety.helpers import check_merge_state, update_pr_branch

branches_updated = 0
branch_update_results = []
branch_update_warnings = []

for pr in branch_update_queue:
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    repo_full = f"{base_owner}/{base_repo_name}"
    pr_number = pr["number"]
    merge_state = pr.get("mergeStateStatus", "UNKNOWN").upper()

    try:
        # Live-check merge state via pr-safety helper to confirm stale status
        state_data = check_merge_state(repo_full, pr_number)
        mergeable_state = state_data.get("mergeable_state", "")
        rebaseable = state_data.get("rebaseable", False)

        if mergeable_state in ("behind", "unknown"):
            if rebaseable:
                # Update branch via pr-safety helper (wraps gh api -X PUT .../update-branch)
                update_pr_branch(repo_full, pr_number)
                branches_updated += 1
                branch_update_results.append({
                    "repo": repo_full, "pr": pr_number,
                    "result": "branch_updated",
                    "head_sha": pr["headRefOid"][:8],
                    "prior_state": merge_state,
                })
                print(f"  ↑ updated branch: {repo_full}#{pr_number} (was {merge_state} — CI will re-run)")
            else:
                print(f"  WARNING: {repo_full}#{pr_number} is {merge_state} but not rebaseable (manual resolution needed)")
                branch_update_results.append({
                    "repo": repo_full, "pr": pr_number,
                    "result": "skipped",
                    "skip_reason": "not_rebaseable",
                    "prior_state": merge_state,
                })
                branch_update_warnings.append({
                    "repo": repo_full, "pr": pr_number, "error": "not_rebaseable"
                })
        elif mergeable_state == "clean":
            # Race condition: branch was updated between scan and execution.
            # Promote to candidates[] for auto-merge in Step 6.
            print(f"  ✓ {repo_full}#{pr_number} is now CLEAN (updated between scan and execution) — promoting to auto-merge")
            candidates.append(pr)
        else:
            # dirty, has_hooks, blocked, etc. — skip with info
            print(f"  — {repo_full}#{pr_number} mergeable_state={mergeable_state} — skipping branch update")
            branch_update_results.append({
                "repo": repo_full, "pr": pr_number,
                "result": "skipped",
                "skip_reason": f"mergeable_state_{mergeable_state}",
                "prior_state": merge_state,
            })

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        print(f"  WARNING: Failed to check/update merge state for {repo_full}#{pr_number}: {error_msg}")
        branch_update_results.append({
            "repo": repo_full, "pr": pr_number,
            "result": "failed", "error": error_msg,
        })
        branch_update_warnings.append({
            "repo": repo_full, "pr": pr_number, "error": error_msg
        })
    except Exception as e:
        print(f"  WARNING: Exception checking merge state for {repo_full}#{pr_number}: {e}")
        branch_update_results.append({
            "repo": repo_full, "pr": pr_number,
            "result": "failed", "error": str(e),
        })
        branch_update_warnings.append({
            "repo": repo_full, "pr": pr_number, "error": str(e)
        })

if branches_updated:
    print(f"\n  Updated {branches_updated} stale branch(es). Next sweep pass will handle them after CI completes.")
```

**Why update BEFORE auto-merge (not after)?**
- With `strict: true` branch protection, auto-merge deadlocks on BEHIND PRs: it waits for
  the branch to be current, but never triggers the update itself.
- Updating first lets CI re-run on the fresh merge commit. The NEXT sweep pass will find
  these PRs in CLEAN state and arm auto-merge normally.
- This avoids wasting GitHub auto-merge slots on PRs that cannot proceed.

**Edge cases:**
- `rebaseable: false` — skip with warning (PR has conflicts that prevent automatic update; may need Track B)
- Rate limiting — sequential processing avoids burst; if `update-branch` returns 403/429, log and continue
- Cascading updates — when multiple PRs target the same repo, updating one may push `main` forward and make others BEHIND again. This is expected; subsequent sweeps handle it.
- Race condition (CLEAN at execution time) — if the branch was updated between scan and execution, promote the PR to `candidates[]` for normal auto-merge processing.

---

## Step 5c — Resolve CodeRabbit Review Threads (Pre-Merge)

Before enabling auto-merge or enqueuing into the merge queue, resolve all unresolved
CodeRabbit review threads. Branch protection requires all review threads resolved
before the merge queue accepts PRs, and CodeRabbit posts 5-20 automated comments
per PR that would otherwise block enqueue.

Process all candidates and branch-update-promoted PRs. Idempotent — safe to call
on PRs with no CodeRabbit threads.

```python
# Uses resolve_coderabbit_threads() from @_lib/pr-safety/helpers.md
from plugins.onex.skills._lib.pr_safety.helpers import resolve_coderabbit_threads

coderabbit_results = []

for pr in candidates:
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    repo_full = f"{base_owner}/{base_repo_name}"
    pr_number = pr["number"]

    try:
        cr_result = resolve_coderabbit_threads(repo_full, pr_number)
        coderabbit_results.append({
            "repo": repo_full, "pr": pr_number, **cr_result
        })
    except Exception as e:
        print(f"  WARNING: Failed to resolve CodeRabbit threads on {repo_full}#{pr_number}: {e}")
        coderabbit_results.append({
            "repo": repo_full, "pr": pr_number,
            "threads_found": 0, "threads_resolved": 0,
            "errors": [{"thread_id": "unknown", "error": str(e)}],
        })
        # Non-fatal: continue to auto-merge attempt — branch protection will catch if threads remain

total_cr_resolved = sum(r["threads_resolved"] for r in coderabbit_results)
if total_cr_resolved > 0:
    print(f"\n  Resolved {total_cr_resolved} CodeRabbit review thread(s) across {len(candidates)} PR(s).")
```

---

## Step 6 — Phase A: Enable GitHub Auto-Merge (Parallel)

For each PR in `candidates[]`, acquire a claim and enable GitHub auto-merge.
Run up to `--max-parallel-prs` concurrently.

**Note**: PRs that were BEHIND/UNKNOWN at scan time have already been handled in Step 5b.
Only PRs with `mergeStateStatus` of CLEAN/HAS_HOOKS/UNSTABLE (or promoted from Step 5b
race conditions) reach this step.

```python
from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry, canonical_pr_key

registry = ClaimRegistry()
auto_merge_results = []

for pr in candidates:
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    repo_full = f"{base_owner}/{base_repo_name}"
    pr_key = canonical_pr_key(org=base_owner, repo=base_repo_name, number=pr["number"])

    # OMN-6468: Skip PRs already in the merge queue. Dequeue/re-enqueue
    # doubles CI time because both runs execute sequentially.
    if pr.get("mergeQueueEntry") is not None or pr.get("mergeStateStatus", "").upper() == "QUEUED":
        auto_merge_results.append({
            "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
            "result": "skipped", "reason": "already in merge queue (OMN-6468)"
        })
        print(f"  ⊘ skipped (in merge queue): {repo_full}#{pr['number']} — {pr.get('title', '')[:60]}")
        continue

    acquired = registry.acquire(pr_key, run_id=run_id, action="auto_merge_enable", dry_run=dry_run)
    if not acquired:
        auto_merge_results.append({
            "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
            "result": "failed", "error": "claim_race_condition"
        })
        continue

    try:
        # QPM: check if this PR has qpm-accelerate label (auto-applied during classification)
        pr_labels = {l["name"] for l in pr.get("labels", [])}
        is_accelerator = "qpm-accelerate" in pr_labels

        # Detect merge queue: repos with merge queues need enqueue_to_merge_queue()
        # from _lib/pr-safety/helpers.md — `gh pr merge --auto` does NOT enqueue
        # into merge queues. (OMN-5635)
        # Repos without merge queues continue using `gh pr merge --auto` as before.
        if has_merge_queue(repo_full):
            # Use pr-safety helper: enqueue_to_merge_queue(repo_full, pr_number)
            # Accelerator PRs get jump=true for priority placement in merge queue
            enqueue = enqueue_to_merge_queue(repo_full, pr["number"], jump=is_accelerator)

            if enqueue["status"] == "enqueued":
                auto_merge_results.append({
                    "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                    "result": "auto_merge_set", "head_sha": pr["headRefOid"][:8]
                })
                print(f"  ✓ enqueued in merge queue: {repo_full}#{pr['number']} — {pr['title'][:60]}")
            elif enqueue["status"] == "unresolved_conversations":
                # Unresolved review threads block enqueue — needs CodeRabbit resolution (OMN-5634)
                auto_merge_results.append({
                    "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                    "result": "failed", "error": "unresolved_conversations — resolve CodeRabbit threads then retry"
                })
                print(f"  ✗ unresolved conversations block enqueue: {repo_full}#{pr['number']} — resolve review threads (OMN-5634) then retry")
            else:
                auto_merge_results.append({
                    "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                    "result": "failed", "error": enqueue.get("error", "unknown enqueue failure")
                })
                print(f"  ✗ failed to enqueue: {repo_full}#{pr['number']} — {enqueue.get('error', 'unknown')}")
        else:
            # No merge queue — use gh pr merge --auto with explicit strategy
            merge_cmd = [
                "gh", "pr", "merge", str(pr["number"]),
                "--repo", repo_full,
                f"--{merge_method}", "--auto",
            ]

            # Enable GitHub auto-merge — merges automatically when all required checks pass
            result = run(merge_cmd)
            if result.returncode == 0:
                auto_merge_results.append({
                    "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                    "result": "auto_merge_set", "head_sha": pr["headRefOid"][:8]
                })
                print(f"  ✓ auto-merge enabled: {repo_full}#{pr['number']} — {pr['title'][:60]}")
            elif "Pull request is in clean status" in (result.stderr or ""):
                # PR is immediately mergeable — GitHub rejects --auto because
                # there's nothing to wait for. Fall back to direct merge.
                direct_cmd = [
                    "gh", "pr", "merge", str(pr["number"]),
                    "--repo", repo_full,
                    f"--{merge_method}",
                ]
                direct_result = run(direct_cmd)
                if direct_result.returncode == 0:
                    auto_merge_results.append({
                        "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                        "result": "merged_directly", "head_sha": pr["headRefOid"][:8]
                    })
                    print(f"  ✓ merged directly: {repo_full}#{pr['number']} — {pr['title'][:60]} (auto-merge unavailable, PR was clean)")
                else:
                    auto_merge_results.append({
                        "pr_key": pr_key, "repo": repo_full, "pr": pr["number"],
                        "result": "failed", "error": direct_result.stderr.strip()
                    })
                    print(f"  ✗ direct merge also failed: {repo_full}#{pr['number']} — {direct_result.stderr.strip()}")
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

## Step 6a — Post-Merge Safety: Update Remaining BEHIND Branches (Sequential)

Safety net for PRs that were CLEAN at scan time but became BEHIND between scan and
auto-merge (e.g., another PR merged to main during this sweep). This is a fallback;
most BEHIND detection now happens proactively in Step 5b.

Process sequentially (not parallel) to respect GitHub API rate limits.

```python
# Uses check_merge_state() and update_pr_branch() from @_lib/pr-safety/helpers.md
from plugins.onex.skills._lib.pr_safety.helpers import check_merge_state, update_pr_branch

post_merge_branches_updated = 0

for result in auto_merge_results:
    if result["result"] != "auto_merge_set":
        continue  # only check PRs where auto-merge was successfully enabled

    repo_full = result["repo"]
    pr_number = result["pr"]

    try:
        state_data = check_merge_state(repo_full, pr_number)
        mergeable_state = state_data.get("mergeable_state", "")
        rebaseable = state_data.get("rebaseable", False)

        if mergeable_state == "behind":
            if rebaseable:
                update_pr_branch(repo_full, pr_number)
                post_merge_branches_updated += 1
                branches_updated += 1
                print(f"  ↑ updated branch (post-merge): {repo_full}#{pr_number} (became behind during sweep)")
            else:
                print(f"  WARNING: {repo_full}#{pr_number} is behind but not rebaseable (manual resolution needed)")
                branch_update_warnings.append({
                    "repo": repo_full, "pr": pr_number, "error": "not_rebaseable"
                })

    except subprocess.CalledProcessError as e:
        print(f"  WARNING: Failed to check/update merge state for {repo_full}#{pr_number}: {e.stderr.strip() if e.stderr else str(e)}")
        branch_update_warnings.append({
            "repo": repo_full, "pr": pr_number, "error": e.stderr.strip() if e.stderr else str(e)
        })
    except Exception as e:
        print(f"  WARNING: Exception checking merge state for {repo_full}#{pr_number}: {e}")
        branch_update_warnings.append({
            "repo": repo_full, "pr": pr_number, "error": str(e)
        })

if post_merge_branches_updated:
    print(f"\n  Updated {post_merge_branches_updated} branch(es) that became stale during sweep.")
```

**Edge cases:**
- Cascading updates — when multiple PRs target the same repo, updating one may push `main` forward and make others BEHIND again. This is expected; subsequent sweeps handle it.

---

## Step 7 — Phase B: Polish PRs with Blocking Issues (Parallel, Concurrent with Phase A)

**Concurrency note (F34):** Phase B runs concurrently with Steps 5b, 6, and 6a (Phase A).
After classification (Step 3), the empty check (Step 4), and the dry-run check (Step 5),
dispatch Phase A (Steps 5b + 6 + 6a) and Phase B (Step 7) as parallel Agent calls in a
single message. This eliminates the sequential bottleneck where Phase B waited for all
Phase A merges to complete before starting polish work.

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
    pr_number = pr["number"]

    # DEFENSE LAYER 1 (OMN-6253): Always fetch the actual PR branch name from the API.
    # Never trust the scan-time headRefName — it may be stale or the dispatcher may
    # have interpolated it incorrectly (caused ~2 hours of wasted polish cycles on 2026-03-24).
    branch = run(f"gh pr view {pr_number} --repo {repo_full} --json headRefName --jq .headRefName").strip()
    if not branch:
        # Fallback to scan data only if API call fails
        branch = pr["headRefName"]
        print(f"WARNING: Could not fetch headRefName from API for {repo_full}#{pr_number}, "
              f"falling back to scan-time value: {branch}")
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

   # MANDATORY: pre-commit hooks are not inherited by worktrees.
   # Run this before any commit; without it hooks are silently skipped.
   pre-commit install
   ```

2. Run pr-polish from inside the worktree:
   ```
   Skill(skill="onex:pr_polish", args="{pr_number} --required-clean-runs {polish_clean_runs}")
   ```
   pr-polish will resolve conflicts, fix CI failures and review comments, run local-review loop, and push.

3. After pr-polish completes, check if the PR is now merge-ready:
   ```bash
   gh pr view {pr_number} --repo {repo_full} --json mergeable,statusCheckRollup,reviewDecision
   ```
   Parse the result using is_merge_ready() logic (mergeable=MERGEABLE, all required CI green, reviewDecision in APPROVED/None).

4. If merge-ready: enqueue or enable auto-merge depending on merge queue presence:
   - **With merge queue** (OMN-5635): Call `enqueue_to_merge_queue(repo_full, pr_number)`
     from `_lib/pr-safety/helpers.md`. This handles the GraphQL `enqueuePullRequest`
     mutation, node ID resolution, and error classification.
     If enqueue returns `"unresolved_conversations"`,
     record as failed with note to resolve CodeRabbit threads (OMN-5634) then retry.
   - **Without merge queue**: Use `gh pr merge --{merge_method} --auto` as before.
     If this fails with "Pull request is in clean status", fall back to direct merge:
     ```bash
     gh pr merge {pr_number} --repo {repo_full} --{merge_method}
     ```
   Record `"merged_directly": true` instead of `"auto_merge_set": true` when directly merged.

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
  "merged_directly": true | false,
  "error": null | "<error message>"
}}"""
        )
    finally:
        registry.release(pr_key, run_id=run_id, dry_run=dry_run)
```

Wait for all polish agents to complete. Collect results into `polish_results[]`.

---

## 7a. Synchronization Barrier (F34)

**Wait for both Track A and Track B agents to complete before collecting results.**

Both Phase A (Steps 5b + 6 + 6a) and Phase B (Step 7) were dispatched concurrently.
Do not proceed to Step 8 until all parallel agents from both tracks have returned.
This ensures `auto_merge_results`, `branch_update_results`, and `polish_results` are
all fully populated before computing aggregate counts and status.

---

## 8. Collect Results

```python
# Step 5b results
proactive_branch_updated_count = sum(1 for r in branch_update_results if r["result"] == "branch_updated")
proactive_branch_failed_count = sum(1 for r in branch_update_results if r["result"] == "failed")

# Step 6 results
auto_merge_set_count = sum(1 for r in auto_merge_results if r["result"] == "auto_merge_set")
merged_directly_count = sum(1 for r in auto_merge_results if r["result"] == "merged_directly")
auto_merge_failed_count = sum(1 for r in auto_merge_results if r["result"] == "failed")

# Step 7 results
polish_done_count = sum(1 for r in polish_results if r.get("polish_status") == "DONE")
polish_partial_count = sum(1 for r in polish_results if r.get("polish_status") == "PARTIAL")
polish_blocked_count = sum(1 for r in polish_results if r.get("polish_status") == "BLOCKED")
polish_auto_merged_count = sum(1 for r in polish_results if r.get("auto_merge_set"))

skipped_count = (
    len(skipped_filtered)
    + sum(1 for r in polish_results if r.get("result") == "skipped")
    + sum(1 for r in branch_update_results if r.get("result") == "skipped")
    + len(hard_failed_claims)
)

total_auto_merge_set = auto_merge_set_count + polish_auto_merged_count
total_merged_directly = merged_directly_count
total_branches_updated = branches_updated  # from Step 5b + Step 6a
total_failed = auto_merge_failed_count + polish_blocked_count + proactive_branch_failed_count

total_successful = total_auto_merge_set + total_merged_directly
if total_successful > 0 and total_failed == 0:
    status = "queued"
elif total_successful > 0 and total_failed > 0:
    status = "partial"
elif total_branches_updated > 0 and total_successful == 0 and total_failed == 0:
    status = "queued"  # branch updates are progress — next sweep will merge
elif total_successful == 0 and total_failed > 0:
    status = "error"
else:
    status = "nothing_to_merge"  # all candidates were skipped or blocked

# Merge scan_failure_details into the details list
# scan_failure_details populated by the post-scan coverage assertion in Step 3
all_details = scan_failure_details + branch_update_results + auto_merge_results + polish_results
```

---

## 9. Post Sweep Summary to Slack

Post a LOW_RISK informational summary. No polling — this is notification only.
Best-effort: if posting fails, log warning and continue.

```bash
source ~/.omnibase/.env 2>/dev/null || true
# If Slack credentials missing, skip notification (not a hard failure)
```

```python
summary_lines = [
    f"*[merge-sweep]* run {run_id} complete\n",
    f"Repos scanned: {repos_scanned} ok | {repos_failed} failed",
    f"Branch updates (proactive):    {proactive_branch_updated_count} stale → updated (CI re-running)",
    f"Track A (auto-merge enabled):  {auto_merge_set_count} PRs queued | {merged_directly_count} merged directly | {auto_merge_failed_count} failed",
    f"  Post-merge branch updates:   {post_merge_branches_updated} behind → updated",
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

queued_prs = [r for r in auto_merge_results + polish_results if r.get("result") in ("auto_merge_set", "merged_directly") or r.get("auto_merge_set")]
if queued_prs:
    summary_lines.append("\nAuto-merge enabled / merged directly:")
    for r in queued_prs:
        if r.get("result") == "merged_directly":
            origin = " (merged directly — no merge queue)"
        elif r.get("auto_merge_set") and r not in auto_merge_results:
            origin = " (after polish)"
        else:
            origin = ""
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

if scan_failure_details:
    summary_lines.append(f"\n⚠️ Scan failures ({repos_failed} repo(s) not scanned — check gh auth/network):")
    for d in scan_failure_details:
        summary_lines.append(f"  • {d['repo']} — {d['error']}")

summary_lines.append(f"\nStatus: {status} | Run: {run_id}")

summary_message = "\n".join(summary_lines)

try:
    post_to_slack(summary_message, channel=SLACK_CHANNEL_ID, bot_token=SLACK_BOT_TOKEN)
except Exception as e:
    print(f"WARNING: Failed to post summary to Slack: {e}", file=sys.stderr)
    # Do NOT fail the skill result — summary is best-effort
```

---

## 10. Emit ModelSkillResult

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
  "repos_scanned": <repos_scanned>,
  "repos_failed": <repos_failed>,
  "candidates_found": <N>,
  "branch_update_queue_found": <B>,
  "polish_queue_found": <M>,
  "auto_merge_set": <count>,
  "merged_directly": <total_merged_directly>,
  "branches_updated": <total_branches_updated>,
  "branches_updated_proactive": <proactive_branch_updated_count>,
  "branches_updated_post_merge": <post_merge_branches_updated>,
  "polished": <polish_done_count>,
  "polish_partial": <polish_partial_count>,
  "polish_blocked": <polish_blocked_count>,
  "skipped": <count>,
  "failed": <count>,
  "details": [
    {
      "repo": "<repo>",
      "pr": null,
      "head_sha": null,
      "track": null,
      "result": "scan_failed",
      "error": "scan never returned (silent miss in parallel fan-out)"
    },
    {
      "repo": "<repo>",
      "pr": <pr_number>,
      "head_sha": "<sha>",
      "track": "A-update | A | B",
      "result": "branch_updated | auto_merge_set | merged_directly | polished_and_queued | polished_partial | blocked | failed | skipped",
      "merge_method": "<method>",
      "prior_state": null | "BEHIND" | "UNKNOWN",
      "skip_reason": null | "UNKNOWN_state" | "since_filter" | "label_filter" | "active_claim" | "draft" | "not_rebaseable"
    }
  ]
}
```

Write result to: `$ONEX_STATE_DIR/skill-results/<run_id>/merge-sweep.json`

Print summary:

```
Merge Sweep Complete — run <run_id>

  Branch updates (proactive):    <proactive_branch_updated_count> stale → updated (CI re-running)
  Track A (auto-merge enabled):  <auto_merge_set_count> queued | <merged_directly_count> merged directly | <auto_merge_failed_count> failed
    Post-merge branch updates:   <post_merge_branches_updated> behind → updated
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
| PR is BEHIND/UNKNOWN at scan time | Step 5b: update branch proactively, skip auto-merge (CI needs to re-run) |
| PR becomes CLEAN between scan and Step 5b | Promote to `candidates[]` for normal auto-merge in Step 6 |
| PR is BEHIND but not rebaseable | Skip with warning; may need Track B or manual resolution |
| `update-branch` API fails (403/429) | Log warning, record `result: failed`, continue others |
| GraphQL `enqueuePullRequest` fails with unresolved conversations | Record `result: failed` with note to resolve CodeRabbit threads (OMN-5634), continue others |
| GraphQL `enqueuePullRequest` fails for other reasons | Record `result: failed` in details, continue others |
| `gh pr merge --auto` fails with "clean status" (non-queue repos) | Fall back to direct `gh pr merge` (no `--auto`); record `result: merged_directly` |
| `gh pr merge --auto` fails for other reasons (non-queue repos) | Record `result: failed` in details, continue others |
| PR becomes BEHIND after auto-merge armed (Step 6a) | Safety net: update branch post-merge |
| pr-polish BLOCKED (conflicts unresolvable) | Record `result: blocked`, skip auto-merge for that PR |
| pr-polish PARTIAL (max iterations hit) | Record `result: polished_partial`, skip auto-merge |
| Worktree creation fails | Record `result: failed`, release claim, continue others |
| Worktree cleanup fails | Log warning, do NOT fail the skill result |
| Slack summary post fails | Log warning only; do NOT fail skill result |
| Claim race condition | Record `result: failed, error: claim_race_condition` |
| Cascading BEHIND after branch update | Expected; subsequent sweeps handle remaining BEHIND PRs |

---

## Composability

This skill can be called directly or from other orchestrators:

```
Skill(skill="onex:merge_sweep", args={
  repos: <scope>,
  max_total_merges: <cap>,
  max_parallel_prs: <cap>,
  max_parallel_polish: <cap>,
  merge_method: <method>,
  since: <date>,                  # optional date filter
  label: <label>,                 # optional label filter
  run_id: <pipeline_run_id>,      # claim registry ownership
  dry_run: <dry_run>,             # propagates to claim registry (zero writes)
  skip_polish: false              # set true to skip Track B
})
```
