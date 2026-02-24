---
name: merge-sweep
description: Org-wide PR merge sweep — scans all repos for merge-ready PRs and merges them in parallel after a single HIGH_RISK Slack gate
version: 2.0.0
category: workflow
tags:
  - pr
  - github
  - merge
  - autonomous
  - pipeline
  - high-risk
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all repos in omni_home)
    required: false
  - name: --dry-run
    description: Print merge candidates without posting Slack gate or merging
    required: false
  - name: --no-gate
    description: Skip Slack gate; requires --gate-token (immediate error if absent)
    required: false
  - name: --gate-token
    description: "Gate token from prior gate run (format: <slack_ts>:<run_id>); required with --no-gate"
    required: false
  - name: --merge-method
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: --require-approval
    description: Require GitHub review approval (default: true)
    required: false
  - name: --require-up-to-date
    description: "Branch update policy: always | never | repo (default: repo — respect branch protection)"
    required: false
  - name: --max-total-merges
    description: Hard cap on total merges per run (default: 10)
    required: false
  - name: --max-parallel-prs
    description: Concurrent merge agents (default: 5)
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel (default: 3)
    required: false
  - name: --authors
    description: Limit to PRs by these GitHub usernames (comma-separated; default: all)
    required: false
  - name: --since
    description: "Filter PRs updated after this date (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ). Avoids sweeping ancient PRs."
    required: false
  - name: --label
    description: "Filter PRs that have this GitHub label. Use comma-separated for multiple (any match). Default: all labels"
    required: false
  - name: --gate-timeout-minutes
    description: "Override Slack gate timeout (default: 1440 = 24h for HIGH_RISK)"
    required: false
inputs:
  - name: repos
    description: "list[str] — repo names to scan; empty list means all"
  - name: gate_token
    description: "str | None — pre-issued gate token for --no-gate mode"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: merged | nothing_to_merge | gate_rejected | partial | error"
---

# Merge Sweep

## Overview

Composable skill that scans all repos in `omni_home` for open PRs that are merge-ready,
batches them into a single HIGH_RISK Slack gate, and merges all approved candidates in
parallel. Designed as the daily close-out command — one human approval drains the entire
merge queue.

**Announce at start:** "I'm using the merge-sweep skill."

**SAFETY INVARIANT**: Merge is a HIGH_RISK action. Silence is NEVER consent for
this gate. Explicit approval required unless `--no-gate` is passed with a valid `--gate-token`.

## Quick Start

```
/merge-sweep                                      # Scan all repos, post gate, merge
/merge-sweep --dry-run                            # Print candidates only (no gate, no merge)
/merge-sweep --repos omniclaude,omnibase_core     # Limit to specific repos
/merge-sweep --no-gate --gate-token 1740312612.000100:20260223-143012-a3f  # Bypass gate
/merge-sweep --authors jonahgabriel               # Only PRs by this author
/merge-sweep --max-total-merges 5                 # Cap at 5 merges
/merge-sweep --merge-method merge                 # Use merge commit (not squash)
/merge-sweep --since 2026-02-01                   # Only PRs updated after Feb 1, 2026
/merge-sweep --since 2026-02-23T00:00:00Z         # Only PRs updated after midnight UTC
/merge-sweep --label ready-for-merge              # Only PRs with this label
/merge-sweep --label ready-for-merge,approved     # PRs with either label
/merge-sweep --since 2026-02-20 --label ready-for-merge  # Combine filters
```

## PR Readiness Predicate

```python
def is_merge_ready(pr, require_approval=True) -> bool:
    if pr["mergeable"] != "MERGEABLE":
        return False
    if not is_green(pr):
        return False
    if require_approval:
        # APPROVED = explicit approval; None = no review required by branch policy
        return pr.get("reviewDecision") in ("APPROVED", None)
    return True  # --require-approval false: skip review check entirely

def is_green(pr) -> bool:
    required_checks = [c for c in pr["statusCheckRollup"] if c.get("isRequired")]
    if not required_checks:
        return True  # no required checks = green
    return all(c.get("conclusion") == "SUCCESS" for c in required_checks)
```

`mergeable == "UNKNOWN"` — skip with warning (GitHub is computing merge state). Not an error.
`mergeable == "CONFLICTING"` — skip silently (handled by fix-prs).

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--dry-run` | false | Print candidates without posting Slack gate or merging |
| `--no-gate` | false | Skip Slack gate; requires `--gate-token` (immediate error if absent) |
| `--gate-token` | — | Required with `--no-gate`; format: `<slack_ts>:<run_id>` |
| `--merge-method` | `squash` | `squash` \| `merge` \| `rebase` |
| `--require-approval` | true | Require at least one GitHub APPROVED review |
| `--require-up-to-date` | `repo` | `always` \| `never` \| `repo` (respect branch protection) |
| `--max-total-merges` | 10 | Hard cap on merges per run |
| `--max-parallel-prs` | 5 | Concurrent merge agents |
| `--max-parallel-repos` | 3 | Repos scanned in parallel |
| `--authors` | all | Limit to PRs by these GitHub usernames (comma-separated) |
| `--since` | — | Filter PRs updated after this date (ISO 8601). Skips ancient PRs. |
| `--label` | all | Filter PRs with this label. Comma-separated = any match. |
| `--gate-timeout-minutes` | 1440 | Override gate timeout (default: 24h) |

## Execution Algorithm

```
1. VALIDATE: if --no-gate and --gate-token is absent → error immediately, do not proceed

2. SCAN (parallel, up to --max-parallel-repos):
   For each repo:
     gh pr list --repo <repo> --state open --json \
       number,title,mergeable,statusCheckRollup,reviewDecision, \
       headRefName,baseRefName,headRepository,headRefOid,author,labels,updatedAt

3. CLASSIFY:
   For each PR:
     - pr_state_unknown: skip with warning (UNKNOWN mergeable state)
     - is_merge_ready(): candidate for further filtering
     - else: skip silently
   Apply --authors filter if set
   Apply --since filter if set: keep only PRs where updatedAt >= since_date
   Apply --label filter if set: keep only PRs where labels intersect with filter_labels
   Apply --max-total-merges cap to filtered candidates[]

4. If candidates is empty: emit ModelSkillResult(status=nothing_to_merge), exit

5. If --dry-run: print candidates table, exit (no gate, no merge)

6. GATE:
   If --no-gate:
     gate_token = <value of --gate-token>  # already validated in step 1
   Else:
     Post HIGH_RISK Slack gate with candidates summary via chat.postMessage
     Capture thread_ts from response
     Invoke slack_gate_poll.py to poll for reply (OMN-2627)
     Parse reply for subset commands (approve all / approve except / skip / reject)
     If rejected or timeout: emit ModelSkillResult(status=gate_rejected), exit

7. MERGE (parallel, up to --max-parallel-prs):
   For each approved_candidate in approved_candidates:
     Skill(skill="onex:auto-merge", args=...)

8. COLLECT results

9. SUMMARY: Post sweep completion summary to Slack (LOW_RISK, informational)

10. EMIT ModelSkillResult
```

## Slack Gate Message Format

```
[HIGH_RISK] merge-sweep — ready to merge N PRs

Run: <run_id>
Scope: <repos> | <author filter if set> | <since filter if set> | <label filter if set>

MERGE CANDIDATES (N PRs, max <max_total_merges>):
  • OmniNode-ai/omniclaude#247 — feat: auto-detect (5 ✓, approved) SHA: cbca770e
  • OmniNode-ai/omnibase_core#88 — fix: validator (3 ✓, no review required) SHA: ff3ab12c

SKIPPED (UNKNOWN state — will retry on next run):
  • OmniNode-ai/omnidash#19 (mergeable: UNKNOWN)

Commands:
  approve all                        — merge all N PRs
  approve except omniclaude#247      — merge all except listed
  skip omniclaude#247                — exclude specific PR, merge rest
  reject                             — cancel entire sweep

This is HIGH_RISK — silence will NOT auto-advance.
```

## Reply Polling (OMN-2627)

After posting the HIGH_RISK gate via `chat.postMessage` (which returns `thread_ts`),
the gate reply is polled using `slack_gate_poll.py` from the `slack-gate` skill:

```bash
python3 /path/to/plugins/onex/skills/slack-gate/slack_gate_poll.py \
  --channel "$SLACK_CHANNEL_ID" \
  --thread-ts "$THREAD_TS" \
  --bot-token "$SLACK_BOT_TOKEN" \
  --timeout-minutes "$GATE_TIMEOUT_MINUTES" \
  --accept-keywords '["approve", "merge", "yes", "proceed"]' \
  --reject-keywords '["reject", "cancel", "no", "hold", "deny"]'
```

The poll script monitors the thread for a qualifying reply. Once received:
- Reply `"approve all"` or `"merge"` → merge all candidates
- Reply `"approve except <repo>#<pr>"` → exclude listed PRs, merge rest
- Reply `"skip <repo>#<pr>"` → same as approve-except
- Reply `"reject"` or `"cancel"` → exit with `status: gate_rejected`

**Poll exit codes:**
- 0 (ACCEPTED): parse reply text for subset commands, then merge
- 1 (REJECTED): exit with `status: gate_rejected`
- 2 (TIMEOUT): exit with `status: gate_rejected` (silence never advances HIGH_RISK)

**Credential resolution**: `~/.omnibase/.env` (SLACK_BOT_TOKEN, SLACK_CHANNEL_ID).
See `slack-gate` skill for full credential resolution details.

## --since Date Filter

The `--since` flag filters PRs to only those updated after the given date:

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

def passes_since_filter(pr: dict, since: datetime | None) -> bool:
    if since is None:
        return True
    updated_at = pr.get("updatedAt", "")
    if not updated_at:
        return True  # unknown update time: include (conservative)
    pr_updated = datetime.fromisoformat(updated_at.rstrip("Z")).replace(tzinfo=timezone.utc)
    return pr_updated >= since
```

**Purpose**: Avoids sweeping ancient PRs that may have stale CI or forgotten review state.
A `--since 2026-02-20` filter skips PRs that haven't been touched in 3+ days.

**`gh pr list` includes `updatedAt` in the JSON fields.** No extra API calls needed.

## --label Filter

The `--label` filter keeps only PRs that have at least one of the specified labels:

```python
def passes_label_filter(pr: dict, filter_labels: list[str]) -> bool:
    """Return True if PR has any of the filter labels (or filter is empty)."""
    if not filter_labels:
        return True
    pr_labels = {label["name"] for label in pr.get("labels", [])}
    return bool(pr_labels & set(filter_labels))
```

The `gh pr list` command must include `labels` in the `--json` fields (already required above).

**Example**: `--label ready-for-merge,approved` merges PRs tagged by teammates as sweep-eligible.
This is the recommended workflow for large teams: teammates label PRs, sweep picks them up.

## Sweep Summary Report

After the merge phase completes, post a LOW_RISK summary to Slack (informational, no polling):

```
[merge-sweep] run <run_id> complete

Results:
  Merged:  N PRs
  Failed:  K PRs
  Skipped: M PRs (UNKNOWN state or gate-excluded)

Merged:
  • OmniNode-ai/omniclaude#247 — feat: auto-detect
  • OmniNode-ai/omnibase_core#88 — fix: validator

Failed (manual intervention needed):
  • OmniNode-ai/omnidash#19 — <error>

Status: merged | partial | error
Gate: <gate_token>
```

Post via `chat.postMessage` to the same Slack channel. No reply polling needed (informational).
If posting fails, log warning but do NOT fail the skill result — summary is best-effort.

## Gate Token Contract

```
run_id is generated at sweep start: "<YYYYMMDD-HHMMSS>-<random6>"
gate_token = "<slack_message_ts>:<run_id>"

When called with --no-gate --gate-token <token>:
  - Skip Slack gate entirely
  - Use provided gate_token for audit trail in ModelSkillResult
  - If --gate-token is absent: immediate error (do not proceed)
```

## ModelSkillResult

Written to `~/.claude/skill-results/<run_id>/merge-sweep.json`:

```json
{
  "skill": "merge-sweep",
  "status": "merged | nothing_to_merge | gate_rejected | partial | error",
  "run_id": "20260223-143012-a3f",
  "gate_token": "<slack_ts>:<run_id>",
  "filters": {
    "since": "2026-02-20",
    "labels": ["ready-for-merge"],
    "authors": ["jonahgabriel"],
    "repos": ["OmniNode-ai/omniclaude"]
  },
  "candidates_found": 5,
  "merged": 4,
  "skipped": 1,
  "failed": 0,
  "details": [
    {
      "repo": "OmniNode-ai/omniclaude",
      "pr": 247,
      "head_sha": "cbca770e",
      "result": "merged | skipped | failed",
      "merge_method": "squash",
      "skip_reason": null
    }
  ]
}
```

Status values:
- `merged` — all candidates merged successfully
- `nothing_to_merge` — no merge-ready PRs found (after all filters)
- `gate_rejected` — human rejected the gate (or timeout without approval)
- `partial` — some merged, some failed
- `error` — unrecoverable error before merge phase

## Failure Handling

| Error | Behavior |
|-------|----------|
| `--no-gate` without `--gate-token` | Immediate error; do not scan or merge |
| PR mergeable state UNKNOWN | Skip with warning; include in `skipped` count |
| `gh pr list` fails for a repo | Log warning, skip that repo, continue others |
| Individual merge fails | Record in `details[].result = "failed"`; continue other merges |
| Gate Slack unavailable | Hard stop; return `status: error` (never merge without gate) |
| All merges fail | Return `status: error` |
| Some merges fail | Return `status: partial` |
| Gate timeout (no reply) | Return `status: gate_rejected` (silence never advances HIGH_RISK) |
| `--since` parse error | Immediate error; show format hint |
| Summary post fails | Log warning; do not fail skill result (summary is best-effort) |

## Sub-skills Used

- `slack-gate` (v2.0.0, OMN-2627) — HIGH_RISK gate with `chat.postMessage` + reply polling
- `slack_gate_poll.py` — reply polling helper (part of `slack-gate` skill, OMN-2627)
- `auto-merge` (existing) — per-PR merge execution with `auto_merge: true`

## Changelog

- **v2.0.0** (OMN-2629): Add `--since` date filter, `--label` filter, wire reply polling
  via OMN-2627's `slack_gate_poll.py`, add `--gate-timeout-minutes` override, add post-sweep
  Slack summary report. Add `filters` field to `ModelSkillResult`. Require `updatedAt` and
  `labels` in `gh pr list` JSON fields.
- **v1.0.0** (OMN-2616): Initial implementation.

## See Also

- `fix-prs` skill — repairs conflicting/failing PRs before they can be merge-swept
- `pr-queue-pipeline` skill — orchestrates fix-prs → merge-sweep in sequence
- `auto-merge` skill — single-PR merge sub-skill
- `slack-gate` skill — HIGH_RISK gate implementation (v2.0.0 with reply polling)
- OMN-2616 — initial merge-sweep implementation
- OMN-2627 — slack-gate reply polling (required for gate)
- OMN-2629 — this ticket (date filters, reply polling, summary)
