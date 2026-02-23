# Merge Sweep Orchestration

You are the merge-sweep orchestrator. This prompt defines the complete execution logic.

## Initialization

When `/merge-sweep [args]` is invoked:

1. **Announce**: "I'm using the merge-sweep skill."

2. **Parse arguments** from `$ARGUMENTS`:
   - `--repos <list>` — default: all repos in omni_home
   - `--dry-run` — default: false
   - `--no-gate` — default: false
   - `--gate-token <token>` — required with `--no-gate`
   - `--merge-method <method>` — default: squash
   - `--require-approval <bool>` — default: true
   - `--require-up-to-date <policy>` — default: repo
   - `--max-total-merges <n>` — default: 10
   - `--max-parallel-prs <n>` — default: 5
   - `--max-parallel-repos <n>` — default: 3
   - `--authors <list>` — default: all

3. **Generate run_id**: `<YYYYMMDD-HHMMSS>-<random6>` (e.g., `20260223-143012-a3f`)

---

## Step 1: Pre-Flight Validation

**CRITICAL**: Before any scanning or I/O, validate arguments:

```
IF --no-gate is set AND --gate-token is absent:
  → Print: "ERROR: --no-gate requires --gate-token. Provide a gate token from a prior gate run."
  → Emit ModelSkillResult(status=error, error="--no-gate requires --gate-token")
  → EXIT immediately (do not scan, do not merge)
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
  --json number,title,mergeable,statusCheckRollup,reviewDecision,headRefName,baseRefName,headRepository,headRefOid,author \
  --limit 100
```

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
```

Classification results:
- `is_merge_ready()` → add to `candidates[]`
- `pr_state_unknown()` → add to `skipped_unknown[]` with warning
- Otherwise → ignore (fix-prs handles these)

Apply `--authors` filter: if set, only include PRs where `pr["author"]["login"]` is in the authors list.

Apply `--max-total-merges` cap: truncate `candidates[]` to the cap.

---

## Step 4: Empty Check

```
IF candidates is empty:
  → Print: "No merge-ready PRs found across <N> repos."
  → If skipped_unknown is not empty: print warning about UNKNOWN state PRs
  → Emit ModelSkillResult(status=nothing_to_merge)
  → EXIT
```

---

## Step 5: Dry Run Check

```
IF --dry-run:
  → Print candidates table (see format below)
  → Print: "Dry run complete. No gate posted, no merges performed."
  → Emit ModelSkillResult(status=nothing_to_merge, candidates_found=<N>, merged=0, skipped=0, failed=0)
  → EXIT
```

### Dry Run Output Format

```
MERGE-READY PRs (<count> found, max <max_total_merges>):

  OmniNode-ai/omniclaude
    #247  feat: auto-detect [OMN-2xxx]     5 checks ✓  APPROVED       SHA: cbca770e
    #251  fix: validator skip              3 checks ✓  no review req  SHA: aab12340

  OmniNode-ai/omnibase_core
    #88   fix: null guard in parser        2 checks ✓  APPROVED       SHA: ff3ab12c

SKIPPED (UNKNOWN merge state — GitHub computing):
    OmniNode-ai/omnidash#19

Total: <N> ready to merge, <M> skipped
```

---

## Step 6: Gate Phase

### If `--no-gate` (bypass mode):

```
gate_token = <value of --gate-token argument>
approved_candidates = candidates  # all candidates approved
Print: "Gate bypassed. Using provided gate_token: <gate_token>"
```

### If normal mode (default):

Post HIGH_RISK Slack gate using the `slack-gate` skill:

```
Skill(skill="slack-gate", args={
  gate_id: sha256("<run_id>:merge-sweep")[:12],
  risk: "HIGH_RISK",
  message: """
PR Queue Merge Sweep — run <run_id>

MERGE CANDIDATES (<N> PRs, cap: <max_total_merges>):
<for each candidate:>
  • <repo>#<pr_number> — <title> (<N> ✓, <review_status>) SHA: <sha8>

<if skipped_unknown:>
SKIPPED (UNKNOWN state — will retry on next run):
<for each skipped:>
  • <repo>#<pr_number> (mergeable: UNKNOWN)

Commands:
  approve all                    — merge all <N> PRs
  approve except <repo>#<pr>     — merge all except listed (space-separated)
  skip <repo>#<pr>               — exclude specific PR, merge rest
  reject                         — cancel entire sweep

This is HIGH_RISK — silence will NOT auto-advance.
  """
})
```

Parse the gate response:
- `approve all` → `approved_candidates = candidates`
- `approve except <list>` → remove listed PRs from candidates
- `skip <list>` → remove listed PRs from candidates
- `reject` or `explicit_reject` → emit `ModelSkillResult(status=gate_rejected)`, EXIT

Store: `gate_token = "<slack_message_ts>:<run_id>"`

---

## Step 7: Merge Phase (Parallel)

Dispatch up to `--max-parallel-prs` merge agents concurrently. For each approved_candidate:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Merge PR <repo>#<pr_number>",
  prompt="Merge PR #<pr_number> in repo <repo>.

    Use the auto-merge skill:
    Skill(skill='auto-merge', args={
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

## Step 8: Collect Results and Emit

Build `ModelSkillResult`:

```json
{
  "skill": "merge-sweep",
  "status": "<status>",
  "run_id": "<run_id>",
  "gate_token": "<gate_token>",
  "candidates_found": <N>,
  "merged": <count of successful merges>,
  "skipped": <count of UNKNOWN + gate-excluded>,
  "failed": <count of merge failures>,
  "details": [
    {
      "repo": "<repo>",
      "pr": <pr_number>,
      "head_sha": "<sha>",
      "result": "merged | skipped | failed",
      "merge_method": "<method>",
      "skip_reason": null | "UNKNOWN_state" | "gate_excluded"
    }
  ]
}
```

Status selection:
- All merged successfully → `merged`
- Zero candidates → `nothing_to_merge`
- Gate rejected → `gate_rejected`
- Some merged, some failed → `partial`
- Zero merged (all failed) → `error`

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
| `--no-gate` without `--gate-token` | Immediate error in Step 1, do not proceed |
| `gh pr list` network failure for a repo | Log warning, skip repo, continue others |
| All repos fail to scan | Return `status: error` |
| Individual PR merge fails | Record `result: failed` in details, continue others |
| `auto-merge` agent task failure | Record `result: failed`, continue others |
| Slack unavailable for gate | Return `status: error` — never merge without gate confirmation |

---

## Composability

This skill is designed to be called from `pr-queue-pipeline` in bypass mode:

```
# From pr-queue-pipeline Phase 3:
Skill(skill="merge-sweep", args={
  repos: <scope>,
  no_gate: true,
  gate_token: <pipeline_gate_token>,
  max_total_merges: <cap>,
  max_parallel_prs: <cap>,
  merge_method: <method>
})
```

When called with `--no-gate --gate-token`, the skill skips Step 6 entirely and proceeds
directly to Step 7. The provided `gate_token` appears in the `ModelSkillResult` for audit.
