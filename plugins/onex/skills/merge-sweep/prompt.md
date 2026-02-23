# Merge Sweep Orchestration

You are the merge-sweep orchestrator. This prompt defines the complete execution logic.

## Initialization

When `/merge-sweep [args]` is invoked:

1. **Announce**: "I'm using the merge-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--dry-run` — default: false (zero filesystem writes including claims)
   - `--no-gate` — default: false
   - `--gate-token <token>` — required with `--no-gate`
   - `--merge-method <method>` — default: squash
   - `--require-approval <bool>` — default: true
   - `--require-up-to-date <policy>` — default: repo
   - `--max-total-merges <n>` — default: 10
   - `--max-parallel-prs <n>` — default: 5
   - `--max-parallel-repos <n>` — default: 3
   - `--authors <list>` — default: all
   - `--since <date>` — default: none (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
   - `--label <labels>` — default: all (comma-separated for any-match)
   - `--gate-timeout-minutes <n>` — default: 1440 (24 hours)
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
IF --gate-attestation is set AND token does not match format `<slack_ts>:<run_id>`:
  → Print: "ERROR: --gate-attestation token is invalid. Expected format: <slack_ts>:<run_id>"
  → Emit ModelSkillResult(status=error, error="--gate-attestation token invalid")
  → EXIT immediately (do not scan, do not merge)

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

## Step 3: Scan Phase (Parallel)

Scan up to `--max-parallel-repos` repos concurrently. For each repo:

```bash
gh pr list \
  --repo <repo> \
  --state open \
  --json number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,baseRepository,headRepository,headRefOid,author,labels,updatedAt \
  --limit 100
```

**IMPORTANT**: `labels` and `updatedAt` are required JSON fields for filtering (v2.0.0).

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
    if pr["mergeable"] != "MERGEABLE":
        return False
    if not is_green(pr):
        return False
    if require_approval:
        return pr.get("reviewDecision") in ("APPROVED", None)
    return True

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
- `is_merge_ready()` is True → candidate for further filtering
  - passes `passes_since_filter()` AND `passes_label_filter()` → add to `candidates_pre_claim[]`
  - else → add to `skipped_filtered[]`
- `pr_state_unknown()` → add to `skipped_unknown[]` with warning
- Otherwise → ignore (fix-prs handles these)

### Claim Registry Check (after filter classification)

For each PR in `candidates_pre_claim[]`, check the global claim registry:

```python
from plugins.onex.hooks.lib.pr_claim_registry import (
    ClaimRegistry, canonical_pr_key
)

registry = ClaimRegistry()
candidates = []
hard_failed_claims = []

for pr in candidates_pre_claim:
    # Use the base repo (not head repo) so the claim key is consistent for forked PRs.
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    pr_key = canonical_pr_key(org=base_owner, repo=base_repo_name, number=pr["number"])

    claim = registry.get_claim(pr_key)
    if claim and registry.has_active_claim(pr_key):
        # HARD FAIL — do not merge a PR with an active claim from another run
        hard_failed_claims.append({
            "pr_key": pr_key,
            "claimed_by_run": claim.get("claimed_by_run"),
            "action": claim.get("action"),
            "last_heartbeat_at": claim.get("last_heartbeat_at"),
        })
        print(
            f"[merge-sweep] HARD FAIL: {pr_key} has active claim "
            f"(run: {claim.get('claimed_by_run')}, action: {claim.get('action')}). "
            f"Excluding from merge candidates.",
            flush=True,
        )
    else:
        candidates.append(pr)

if hard_failed_claims:
    print(
        f"[merge-sweep] {len(hard_failed_claims)} PR(s) excluded due to active claims: "
        + ", ".join(h["pr_key"] for h in hard_failed_claims)
    )
```

`hard_failed_claims` are included in the `ModelSkillResult.details[]` with
`skip_reason: "active_claim"` and `result: "skipped"`. They are NOT treated as merge failures
(the merge never attempted) but are prominently logged.

Apply `--authors` filter: if set, only include PRs where `pr["author"]["login"]` is in the authors list.

Apply `--max-total-merges` cap: truncate `candidates[]` to the cap.

---

## Step 4: Empty Check

```
IF candidates is empty:
  → Print: "No merge-ready PRs found across <N> repos."
  → If applicable, explain filters: "Note: --since <date> and/or --label <labels> may have excluded PRs."
  → If skipped_unknown is not empty: print warning about UNKNOWN state PRs
  → Emit ModelSkillResult(status=nothing_to_merge, filters=filters)
  → EXIT
```

---

## Step 5: Dry Run Check

```
IF --dry-run:
  → Print candidates table (see format below)
  → Print: "Dry run complete. No gate posted, no merges performed."
  → Emit ModelSkillResult(status=nothing_to_merge, candidates_found=<N>, merged=0, skipped=0, failed=0, filters=filters)
  → EXIT
```

### Dry Run Output Format

```
MERGE-READY PRs (<count> found, max <max_total_merges>):
Filters: since=<since_date> | labels=<labels> | authors=<authors>

  OmniNode-ai/omniclaude
    #247  feat: auto-detect [OMN-2xxx]     5 checks ✓  APPROVED       SHA: cbca770e  updated: 2026-02-23
    #251  fix: validator skip              3 checks ✓  no review req  SHA: aab12340  updated: 2026-02-22

  OmniNode-ai/omnibase_core
    #88   fix: null guard in parser        2 checks ✓  APPROVED       SHA: ff3ab12c  updated: 2026-02-20

SKIPPED (UNKNOWN merge state — GitHub computing):
    OmniNode-ai/omnidash#19

SKIPPED (filtered by --since or --label):
    OmniNode-ai/omnidash#18  (last updated: 2026-02-01, before --since 2026-02-20)

Total: <N> ready to merge, <M> skipped
```

---

## Step 6: Gate Phase

### Resolve Slack Credentials

```bash
source ~/.omnibase/.env 2>/dev/null || true

if [[ -z "${SLACK_BOT_TOKEN:-}" || -z "${SLACK_CHANNEL_ID:-}" ]]; then
  # Infisical fallback (see slack-gate skill SKILL.md for full snippet)
  echo "ERROR: SLACK_BOT_TOKEN and SLACK_CHANNEL_ID required" >&2
  exit 1
fi
```

### If `--gate-attestation=<token>` (bypass mode):

```
gate_token = <value of --gate-attestation argument>
approved_candidates = candidates  # all candidates approved
Print: "Gate bypassed. Using provided gate_token: <gate_token>"
```

### If normal mode (default):

#### 6a: Post HIGH_RISK gate via chat.postMessage

Build gate message (see SKILL.md for format). Include active filters in the Scope line.

Post via `chat.postMessage`:
```python
import json, urllib.request

payload = json.dumps({
    "channel": SLACK_CHANNEL_ID,
    "text": gate_message,
}).encode("utf-8")

req = urllib.request.Request(
    "https://slack.com/api/chat.postMessage",
    data=payload,
    headers={
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    },
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read())

if not data["ok"]:
    raise RuntimeError(f"chat.postMessage failed: {data.get('error')}")

thread_ts = data["message"]["ts"]
gate_token = f"{thread_ts}:{run_id}"
```

#### 6b: Poll for reply via slack_gate_poll.py

```bash
SKILL_BASE="$(dirname "$(realpath "$0")")"
POLL_SCRIPT="${SKILL_BASE}/../slack-gate/slack_gate_poll.py"

POLL_OUTPUT=$(python3 "$POLL_SCRIPT" \
  --channel "$SLACK_CHANNEL_ID" \
  --thread-ts "$THREAD_TS" \
  --bot-token "$SLACK_BOT_TOKEN" \
  --timeout-minutes "$GATE_TIMEOUT_MINUTES" \
  --accept-keywords '["approve", "merge", "yes", "proceed"]' \
  --reject-keywords '["reject", "cancel", "no", "hold", "deny"]')
POLL_EXIT=$?
```

#### 6c: Parse gate reply

```python
if poll_exit == 1 or poll_exit == 2:
    # Rejected or timeout — never merge without explicit approval
    emit ModelSkillResult(status="gate_rejected", gate_token=gate_token)
    EXIT

# poll_exit == 0: accepted
reply_text = poll_output.removeprefix("ACCEPTED:").strip().lower()

if "reject" in reply_text or "cancel" in reply_text:
    emit ModelSkillResult(status="gate_rejected")
    EXIT

# Parse subset commands
excluded_prs = set()
if "approve except" in reply_text or "skip" in reply_text:
    # Extract PR references: "approve except omniclaude#247 omnibase_core#88"
    # Format: <repo>#<pr_number> (short name or full OmniNode-ai/repo#N)
    import re
    pr_refs = re.findall(r'[\w/-]+#(\d+)', reply_text)
    excluded_prs = {int(n) for n in pr_refs}

approved_candidates = [c for c in candidates if c["number"] not in excluded_prs]
```

---

## Step 7: Merge Phase (Parallel)

Before dispatching each merge agent, **acquire a claim** from the global claim registry.
Release the claim after the merge agent completes (success or failure).

```python
from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry, canonical_pr_key

registry = ClaimRegistry()

for pr in approved_candidates:
    # Use the base repo (not head repo) so the claim key is consistent for forked PRs.
    base_owner, base_repo_name = pr["baseRepository"]["nameWithOwner"].split("/")
    pr_key = canonical_pr_key(org=base_owner, repo=base_repo_name, number=pr["number"])

    acquired = registry.acquire(pr_key, run_id=run_id, action="merge", dry_run=dry_run)
    if not acquired:
        # Race: another run claimed between classification and merge dispatch
        record result: failed, error: "claim_race_condition"
        continue

    try:
        # dispatch merge agent (see Task() block below)
        ...
    finally:
        registry.release(pr_key, run_id=run_id, dry_run=dry_run)
```

Dispatch up to `--max-parallel-prs` merge agents concurrently. For each approved_candidate:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Merge PR <repo>#<pr_number>",
  prompt="Merge PR #<pr_number> in repo <repo>.

    Use the auto-merge skill:
    Skill(skill='onex:auto-merge', args={
      pr: <pr_number>,
      auto_merge: true,
      strategy: '<merge_method>'
    })

    The gate has already been approved. Do NOT post another gate.
    The gate_token for audit is: <gate_token>

    Return the merge result: merged | failed, and any error message."
)
```

Wait for all merge agents to complete. Collect results.

---

## Step 8: Collect Results

Build `details[]` from merge agent results:

```python
merged_count = sum(1 for d in details if d["result"] == "merged")
failed_count = sum(1 for d in details if d["result"] == "failed")
skipped_count = len(skipped_unknown) + len(skipped_filtered) + len(excluded_prs) + len(hard_failed_claims)

if merged_count == len(approved_candidates) and failed_count == 0:
    status = "merged"
elif merged_count > 0 and failed_count > 0:
    status = "partial"
elif merged_count == 0 and failed_count > 0:
    status = "error"
else:
    status = "merged"  # edge case: 0 approved candidates
```

---

## Step 9: Post Sweep Summary to Slack

After collecting results, post a summary message to the Slack channel.
This is informational — no polling, no gate. Best-effort: if posting fails, log warning and continue.

```python
summary_lines = [
    f"*[merge-sweep]* run {run_id} complete\n",
    f"Results:  Merged {merged_count} | Failed {failed_count} | Skipped {skipped_count}",
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

merged_prs = [d for d in details if d["result"] == "merged"]
if merged_prs:
    summary_lines.append("\nMerged:")
    for d in merged_prs:
        summary_lines.append(f"  • {d['repo']}#{d['pr']} — {d.get('title', '')}")

failed_prs = [d for d in details if d["result"] == "failed"]
if failed_prs:
    summary_lines.append("\nFailed (manual intervention needed):")
    for d in failed_prs:
        summary_lines.append(f"  • {d['repo']}#{d['pr']} — {d.get('error', 'unknown error')}")

summary_lines.append(f"\nStatus: {status} | Gate: {gate_token}")

summary_message = "\n".join(summary_lines)

# Post summary (best-effort)
try:
    post_to_slack(summary_message, channel=SLACK_CHANNEL_ID, bot_token=SLACK_BOT_TOKEN)
except Exception as e:
    print(f"WARNING: Failed to post summary to Slack: {e}", file=sys.stderr)
    # Do NOT fail the skill result
```

---

## Step 10: Emit ModelSkillResult

```json
{
  "skill": "merge-sweep",
  "status": "<status>",
  "run_id": "<run_id>",
  "gate_token": "<gate_token>",
  "filters": {
    "since": "<since_str or null>",
    "labels": ["<label1>"],
    "authors": ["<author1>"],
    "repos": ["<repo1>"]
  },
  "candidates_found": <N>,
  "merged": <count>,
  "skipped": <count>,
  "failed": <count>,
  "details": [
    {
      "repo": "<repo>",
      "pr": <pr_number>,
      "head_sha": "<sha>",
      "result": "merged | skipped | failed",
      "merge_method": "<method>",
      "skip_reason": null | "UNKNOWN_state" | "gate_excluded" | "since_filter" | "label_filter" | "active_claim"
    }
  ]
}
```

Write result to: `~/.claude/skill-results/<run_id>/merge-sweep.json`

Print summary:

```
Merge Sweep Complete — run <run_id>
  Merged:   <N> PRs
  Skipped:  <M> PRs
  Failed:   <K> PRs
  Status:   <status>
  Gate:     <gate_token>
```

---

## Error Handling

| Situation | Action |
|-----------|--------|
| `--gate-attestation` with invalid token format | Immediate error in Step 1, do not proceed |
| `--since` parse failure | Immediate error in Step 1, show format hint |
| `gh pr list` network failure for a repo | Log warning, skip repo, continue others |
| All repos fail to scan | Return `status: error` |
| Individual PR merge fails | Record `result: failed` in details, continue others |
| `auto-merge` agent task failure | Record `result: failed`, continue others |
| Slack unavailable for gate | Return `status: error` — never merge without gate confirmation |
| Gate timeout (no reply) | Return `status: gate_rejected` — silence never advances HIGH_RISK |
| Summary post fails | Log warning only; do NOT fail skill result |

---

## Composability

This skill is designed to be called from `pr-queue-pipeline` in bypass mode:

```
# From pr-queue-pipeline Phase 3:
Skill(skill="onex:merge-sweep", args={
  repos: <scope>,
  gate_attestation: <pipeline_gate_token>,
  max_total_merges: <cap>,
  max_parallel_prs: <cap>,
  merge_method: <method>,
  since: <date>,                  # optional date filter
  label: <label>,                 # optional label filter
  run_id: <pipeline_run_id>,      # claim registry ownership
  dry_run: <dry_run>              # propagates to claim registry (zero writes)
})
```

When called with `--gate-attestation=<token>`, the skill skips Step 6 entirely and proceeds
directly to Step 7. The provided `gate_token` appears in the `ModelSkillResult` for audit.
