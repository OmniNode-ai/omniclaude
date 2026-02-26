---
name: integration-gate
description: Cross-repo integration gate — scans repos for merge-ready PRs, classifies into lanes (fast/standard/high_risk), detects cross-repo dependencies, applies topological ordering, and enqueues into GitHub Merge Queue with Slack gate approval
version: 1.0.0
category: workflow
tags:
  - integration
  - merge-queue
  - cross-repo
  - gate
  - pipeline
  - org-wide
  - high-risk
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all repos in omni_home)
    required: false
  - name: --lane
    description: "Lane filter: fast | standard | high_risk | all (default: all)"
    required: false
  - name: --dry-run
    description: Scan, classify, and display plan without mutations; zero enqueue operations
    required: false
  - name: --run-id
    description: Run identifier for state tracking and claim registry (generated if not provided)
    required: false
  - name: --gate-attestation
    description: "Bypass Slack gate with pre-issued token bound to plan (format: <run_id>:<plan_hash>:<slack_ts>)"
    required: false
  - name: --max-queue-size
    description: Maximum PRs to enqueue per run (default: 10)
    required: false
  - name: --require-approval
    description: Require GitHub APPROVED review (default: true)
    required: false
  - name: --authors
    description: Comma-separated GitHub usernames to filter by (default: all)
    required: false
  - name: --since
    description: Filter PRs updated after this date (ISO 8601; default: none)
    required: false
  - name: --label
    description: Comma-separated GitHub labels to filter by (default: all)
    required: false
  - name: --monitor-timeout-minutes
    description: Timeout for merge queue monitoring phase (default: 90)
    required: false
inputs:
  - name: repos
    description: "list[str] -- repo names to scan; empty list means all"
  - name: lane
    description: "str -- lane filter (fast|standard|high_risk|all)"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: queued | merged | partial | nothing_to_queue | gate_rejected | error"
---

# Integration Gate

## Overview

Composable skill that adds cross-repo ordering, lane policy, and observability on top of
GitHub Merge Queue. Where merge-sweep handles merge-ready PRs via `gh pr merge --auto`,
integration-gate orchestrates PRs through the merge queue with:

- **Lane classification**: PRs are classified as fast, standard, or high_risk based on
  file paths, labels, and change volume
- **Cross-repo dependency detection**: Dependency links in PR bodies (`Depends on OmniNode-ai/repo#N`)
  are extracted and used for topological ordering
- **Topological sort with cycle detection**: Fail-fast before any enqueue if circular
  dependencies exist
- **Slack gate**: HIGH_RISK gate with plan table, lane breakdown, and plan_hash
- **GitHub Merge Queue enqueue**: PRs added via `node_git_effect.pr_merge(use_merge_queue=True)`
- **Queue monitoring**: Poll merge state, handle ejections, respect lane-specific retry policies

**Architecture**:
```
/integration-gate                          -- policy + cross-repo ordering
  |
  +-> node_git_effect                      -- typed git operations
  |    +-> HandlerGitSubprocess            -- concrete subprocess backend
  |
  +-> GitHub Merge Queue (per-repo)        -- composition testing
  |
  +-> /slack-gate (inline)                 -- gate posting/polling
  |
  +-> Kafka events (node contract)         -- observability
```

**Announce at start:** "I'm using the integration-gate skill."

## Quick Start

```
/integration-gate                                          # Scan all repos, full pipeline
/integration-gate --dry-run                                # Plan only, no mutations
/integration-gate --repos omniclaude,omnibase_core         # Limit to specific repos
/integration-gate --lane fast                              # Only fast-lane PRs
/integration-gate --dry-run --lane high_risk               # Preview high-risk PRs
/integration-gate --authors jonahgabriel --since 2026-02-01
/integration-gate --gate-attestation=<run_id>:<plan_hash>:<slack_ts>
```

## Lane Classification

PRs are deterministically classified into lanes. First match wins.

```python
import re
from pathlib import Path

HIGH_RISK_LABELS = {"high-risk", "migration", "breaking"}
HIGH_RISK_PATH_PATTERNS = [
    r"^\.github/workflows/",     # CI changes
    r"/migrations/",             # DB migrations
    r"contract\.yaml$",          # ONEX contracts
    r"pyproject\.toml$",         # Dependency/version changes
]

FAST_LABELS = {"docs-only", "chore"}
FAST_ONLY_EXTENSIONS = {".md", ".txt", ".yml", ".yaml"}
WORKFLOW_PATH = re.compile(r"^\.github/workflows/")


def classify_lane(pr: dict) -> tuple[str, str]:
    """Classify a PR into a lane. Returns (lane, reason).

    Lane precedence: high_risk > fast > standard (default).
    Reason is included in the plan table for explainability.
    """
    files = pr.get("files", [])
    labels = {label["name"] for label in pr.get("labels", [])}

    # High-risk checks (first match wins)
    if labels & HIGH_RISK_LABELS:
        return ("high_risk", f"label: {sorted(labels & HIGH_RISK_LABELS)}")
    if len(files) > 20:
        return ("high_risk", f"{len(files)} files changed")
    for f in files:
        path = f.get("path", "") if isinstance(f, dict) else str(f)
        for pattern in HIGH_RISK_PATH_PATTERNS:
            if re.search(pattern, path):
                return ("high_risk", f"touches {path}")

    # Fast checks
    if labels & FAST_LABELS:
        all_safe = all(
            Path(f.get("path", "") if isinstance(f, dict) else str(f)).suffix
            in FAST_ONLY_EXTENSIONS
            and not WORKFLOW_PATH.match(
                f.get("path", "") if isinstance(f, dict) else str(f)
            )
            for f in files
        )
        if all_safe and len(files) <= 3:
            return (
                "fast",
                f"label: {sorted(labels & FAST_LABELS)}, {len(files)} safe files",
            )

    return ("standard", "default")
```

Plan table includes `lane_reason` column for explainability.

## Cross-Repo Dependency Detection

Dependencies are extracted from PR body text using regex patterns:

```python
DEP_PATTERNS = [
    re.compile(r"Depends on (?:https://github\.com/)?OmniNode-ai/(\w+)#(\d+)", re.I),
    re.compile(r"After (?:https://github\.com/)?OmniNode-ai/(\w+)#(\d+)", re.I),
]


def extract_cross_repo_deps(pr_body: str) -> list[tuple[str, int]]:
    """Extract cross-repo dependencies from PR body.

    Returns list of (repo_name, pr_number) tuples.
    """
    deps = []
    for pattern in DEP_PATTERNS:
        for match in pattern.finditer(pr_body or ""):
            deps.append((match.group(1), int(match.group(2))))
    return deps
```

## Cycle Policy

**Deterministic, fail-fast**: On cycle detection, the entire run fails before any enqueue.

- Emit cycle edges in ModelSkillResult output
- Do NOT enqueue non-cycle PRs (partial enqueue creates new conflicts)
- Status: `error` with error type `CROSS_REPO_CYCLE`

## Topological Sort

Tie-break rule for stable ordering: when dependencies do not constrain order, sort by
`(repo_name, pr_number)` ascending. This guarantees identical ordering across repeated
runs with the same input.

## Gate Attestation

Format: `<run_id>:<plan_hash>:<slack_ts>`

- `plan_hash` = SHA-256 of normalized plan table (repo, pr_number, lane, depends_on -- sorted)
- Validation: recompute plan_hash from current state, compare to attestation
- Reject on mismatch (plan changed since approval) with `GATE_PLAN_DRIFT`

## PR Merge Readiness Predicate

Reuses the merge-sweep predicate:

```python
def is_merge_ready(pr: dict, require_approval: bool = True) -> bool:
    """PR is safe to enqueue into merge queue."""
    if pr.get("isDraft"):
        return False
    if pr.get("mergeable") != "MERGEABLE":
        return False
    required_checks = [
        c for c in pr.get("statusCheckRollup", []) if c.get("isRequired")
    ]
    if required_checks and not all(
        c.get("conclusion") == "SUCCESS" for c in required_checks
    ):
        return False
    if require_approval:
        return pr.get("reviewDecision") in ("APPROVED", None)
    return True
```

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names |
| `--lane` | all | `fast` \| `standard` \| `high_risk` \| `all` |
| `--dry-run` | false | Plan only, no mutations |
| `--run-id` | generated | Run identifier |
| `--gate-attestation` | none | Bypass Slack gate (bound to plan_hash) |
| `--max-queue-size` | 10 | Max PRs per run |
| `--require-approval` | true | Require GH APPROVED review |
| `--authors` | all | Filter by GitHub usernames |
| `--since` | none | Filter by ISO 8601 date |
| `--label` | all | Filter by GitHub labels |
| `--monitor-timeout-minutes` | 90 | Queue watch timeout |

## Execution Algorithm

```
1. VALIDATE: parse arguments, validate --since date, validate --gate-attestation format

2. SCAN (parallel, per repo):
   node_git_effect.pr_list() with json_fields:
     number, title, mergeable, statusCheckRollup, reviewDecision,
     headRefName, baseRefName, baseRepository, headRepository,
     headRefOid, author, labels, updatedAt, isDraft, body, files

3. CLASSIFY:
   - Apply filters (--authors, --since, --label)
   - Apply is_merge_ready() predicate
   - Classify into lanes via classify_lane()
   - Extract cross-repo deps from PR body
   - Apply --lane filter
   - Apply --max-queue-size cap

4. DEPENDENCY ANALYSIS:
   - Build dependency graph from extracted deps
   - Run topological sort with (repo_name, pr_number) tie-break
   - On cycle: FAIL with CROSS_REPO_CYCLE (emit cycle edges), exit

5. PLAN DISPLAY:
   - Table: repo | PR | lane | lane_reason | depends_on | action
   - Compute plan_hash (SHA-256 of normalized table)
   - --dry-run exits here with nothing_to_queue status

6. SLACK GATE:
   - Post HIGH_RISK gate with plan table + lane breakdown + plan_hash
   - High-risk PRs individually called out with file paths
   - --gate-attestation bypasses (validated: run_id match, plan_hash match)
   - Rejection -> gate_rejected status, zero mutations

7. ENQUEUE (by lane):
   - Fast lane first: node_git_effect.pr_merge(use_merge_queue=True) per PR
   - Standard lane: topological order, respect cross-repo deps
     - Blocker merges first -> wait -> then blocked PR enters queue
     - Independent PRs added simultaneously
   - High-risk last: one at a time, monitor result before next

8. MONITOR:
   - Poll node_git_effect.pr_view() for merge state
   - On ejection: fetch failing checks, post to Slack thread
   - Lane-specific retry:
     - fast: continue with unrelated repos
     - standard: stop chain when blocker fails
     - high_risk: stop entirely
   - On merge: unblock dependent PRs, update state
   - Timeout: report partial results

9. SUMMARY:
   - Slack LOW_RISK summary (merged/ejected/blocked per lane)
   - Emit ModelSkillResult
   - Emit Kafka event via node contract
```

## ModelSkillResult

Written to `~/.claude/skill-results/<run_id>/integration-gate.json`:

```json
{
  "skill": "integration-gate",
  "status": "queued | merged | partial | nothing_to_queue | gate_rejected | error",
  "run_id": "<run_id>",
  "plan_hash": "<sha256>",
  "filters": {
    "since": "<date or null>",
    "labels": [],
    "authors": [],
    "repos": [],
    "lane": "all"
  },
  "candidates_found": 5,
  "enqueued": 4,
  "merged": 3,
  "ejected": 1,
  "skipped": 0,
  "by_lane": {
    "fast": {"enqueued": 2, "merged": 2, "ejected": 0},
    "standard": {"enqueued": 1, "merged": 1, "ejected": 0},
    "high_risk": {"enqueued": 1, "merged": 0, "ejected": 1}
  },
  "cycle_edges": [],
  "details": [
    {
      "repo": "OmniNode-ai/omniclaude",
      "pr": 247,
      "head_sha": "cbca770e",
      "lane": "fast",
      "lane_reason": "label: ['chore'], 1 safe files",
      "depends_on": [],
      "result": "merged",
      "ejection_reason": null
    }
  ]
}
```

## Error Types

| Error | Description | Behavior |
|-------|-------------|----------|
| `QUEUE_NOT_ENABLED` | Merge queue not enabled on repo | Skip repo, warn |
| `CROSS_REPO_CYCLE` | Circular dependency detected | Fail entire run before enqueue |
| `QUEUE_EJECTION` | PR ejected from merge queue | Lane-specific retry policy |
| `GATE_REJECTED` | Slack gate denied | Zero mutations |
| `GATE_TIMEOUT` | Slack gate timed out | Zero mutations |
| `GATE_PLAN_DRIFT` | Gate attestation plan_hash mismatch | Reject attestation |
| `MONITOR_TIMEOUT` | Queue monitoring timed out | Report partial results |

## Failure Handling

| Error | Behavior |
|-------|----------|
| `node_git_effect.pr_list` fails for a repo | Log warning, skip that repo, continue others |
| `node_git_effect.pr_merge` fails for a PR | Record `result: failed`; lane-specific retry policy |
| Cycle detected | Fail entire run before any enqueue |
| Gate rejected | Zero mutations; `gate_rejected` status |
| Gate attestation invalid | Fail with `GATE_PLAN_DRIFT` |
| Queue ejection (fast lane) | Continue with unrelated repos |
| Queue ejection (standard lane) | Stop the dependency chain |
| Queue ejection (high_risk lane) | Stop entirely |
| Monitor timeout | Report partial results |
| Slack notification fails | Log warning; do NOT fail skill result |

## Sub-skills Used

- `slack-gate` -- gate posting and polling (inline, via `@_lib/slack-gate/helpers.md`)
- `node_git_effect` -- all git/gh operations (typed, structured)

## Dependencies

- `node_git_effect` with `HandlerGitSubprocess` (OMN-2817)
- GitHub Merge Queue enabled on target repos (OMN-2818)
- `@_lib/dependency-tiers/helpers.md` -- tier graph helpers
- `@_lib/run-state/helpers.md` -- state persistence helpers
- `@_lib/slack-gate/helpers.md` -- gate posting/polling helpers

## Changelog

- **v1.0.0** (OMN-2819): Initial implementation.
