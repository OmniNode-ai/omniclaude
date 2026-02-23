---
name: merge-sweep
description: Org-wide PR merge sweep — scans all repos for merge-ready PRs and merges them in parallel after a single HIGH_RISK Slack gate
version: 1.0.0
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
```

## PR Readiness Predicate

```python
def is_merge_ready(pr) -> bool:
    return (
        pr["mergeable"] == "MERGEABLE"
        and is_green(pr)          # all REQUIRED checks have conclusion == "SUCCESS"
        and pr["reviewDecision"] in {"APPROVED", None}
    )

def is_green(pr) -> bool:
    required_checks = [c for c in pr["statusCheckRollup"] if c.get("isRequired")]
    if not required_checks:
        return True  # no required checks = green
    return all(c["conclusion"] == "SUCCESS" for c in required_checks)
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

## Execution Algorithm

```
1. VALIDATE: if --no-gate and --gate-token is absent → error immediately, do not proceed

2. SCAN (parallel, up to --max-parallel-repos):
   For each repo:
     gh pr list --repo <repo> --state open --json \
       number,title,mergeable,statusCheckRollup,reviewDecision, \
       headRefName,baseRefName,headRepository,headRefOid,author

3. CLASSIFY:
   For each PR:
     - pr_state_unknown: skip with warning (UNKNOWN mergeable state)
     - is_merge_ready(): add to candidates[]
     - else: skip silently
   Apply --authors filter if set
   Apply --max-total-merges cap to candidates[]

4. If candidates is empty: emit ModelSkillResult(status=nothing_to_merge), exit

5. If --dry-run: print candidates table, exit (no gate, no merge)

6. GATE:
   If --no-gate:
     gate_token = <value of --gate-token>  # already validated in step 1
   Else:
     Post HIGH_RISK Slack gate with candidates summary
     gate_token = "<slack_message_ts>:<run_id>"
     Wait for explicit approval (HIGH_RISK — silence never advances)
     If rejected: emit ModelSkillResult(status=gate_rejected), exit

7. MERGE (parallel, up to --max-parallel-prs):
   For each approved_candidate in approved_candidates:
     Skill(skill="auto-merge", args={
       pr: <pr_number>,
       repo: <repo>,
       auto_merge: true,
       strategy: <merge_method>,
       gate_token: <gate_token>
     })

8. COLLECT results and emit ModelSkillResult
```

## Slack Gate Message Format

```
[HIGH_RISK] merge-sweep — ready to merge N PRs

Run: <run_id>
Scope: <repos> | <author filter if set>

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
- `nothing_to_merge` — no merge-ready PRs found
- `gate_rejected` — human rejected the gate
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

## Sub-skills Used

- `slack-gate` (existing) — HIGH_RISK gate with explicit approve required
- `auto-merge` (existing) — per-PR merge execution with `auto_merge: true`

## See Also

- `fix-prs` skill — repairs conflicting/failing PRs before they can be merge-swept
- `pr-queue-pipeline` skill — orchestrates fix-prs → merge-sweep in sequence
- `auto-merge` skill — single-PR merge sub-skill
- `slack-gate` skill — HIGH_RISK gate implementation
