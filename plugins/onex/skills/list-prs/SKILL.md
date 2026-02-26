---
name: list-prs
description: Dashboard view of all open (non-draft) PRs across OmniNode-ai repos — shows CI status, mergeable state, and groups PRs by readiness
version: 1.0.0
category: workflow
tags:
  - pr
  - github
  - status
  - dashboard
  - ci
author: OmniClaude Team
composable: true
args:
  - name: --repo
    description: Filter to a single repo by short name (e.g. omniclaude, omnibase_core)
    required: false
  - name: --ready-only
    description: Show only PRs that are merge-ready (green CI, approved, no conflicts)
    required: false
  - name: --include-drafts
    description: Include draft PRs in output (default excluded)
    required: false
outputs:
  - name: skill_result
    description: "Grouped PR dashboard printed to stdout; no file written"
---

# List PRs

## Overview

Scans all open, non-draft PRs across OmniNode-ai repos and prints a grouped dashboard showing
CI status, mergeable state, and review decision. PRs are grouped into five buckets:
READY TO MERGE, FAILING, PENDING, CONFLICTS, and NO CI RUN. Use `--repo` to focus on one
repo or `--ready-only` to filter to actionable PRs only. This skill is read-only: it fetches
data via `gh` but makes no changes to any repo or PR.

**Announce at start:** "I'm using the list-prs skill to scan open PRs."

## Quick Start

```
/list-prs
/list-prs --repo omniclaude
/list-prs --ready-only
/list-prs --repo omnibase_core --ready-only
/list-prs --include-drafts
```

## Repos Scanned (Default)

| Short name | GitHub slug |
|------------|-------------|
| omniclaude | OmniNode-ai/omniclaude |
| omnibase_core | OmniNode-ai/omnibase_core |
| omnibase_infra | OmniNode-ai/omnibase_infra |
| omnibase_spi | OmniNode-ai/omnibase_spi |
| omniintelligence | OmniNode-ai/omniintelligence |
| omnimemory | OmniNode-ai/omnimemory |
| omnidash | OmniNode-ai/omnidash |
| onex_change_control | OmniNode-ai/onex_change_control |

**omninode_infra is excluded by default.** Pass `--repo omninode_infra` to include it explicitly.

## Execution Steps

1. **Resolve repo list**: If `--repo` is given, resolve it to the full `OmniNode-ai/<repo>`
   slug (accepting either the short name or the full slug). Otherwise use the default list above.

2. **Fetch PR data**: For each repo, run:
   ```bash
   gh pr list \
     --repo OmniNode-ai/<repo> \
     --state open \
     --json number,title,author,headRefName,isDraft,mergeable,reviewDecision,statusCheckRollup,createdAt,url \
     --limit 50
   ```
   **Use ONLY the exact fields listed above** — do not add `baseRepository`, `headRepository`,
   or any other fields. The `gh` CLI available in this environment does not support all GraphQL
   fields and will fail with "Unknown JSON field" if extras are added.

   If `--include-drafts` is NOT set, filter out any PR where `isDraft == true`.

3. **Classify each PR** using the rules in the Classification section below.

4. **If `--ready-only`**: discard all PRs except those in the READY TO MERGE bucket.

5. **Print output** using the format in the Output Format section below.

6. **Print summary line** at the end with totals per bucket.

## PR Classification

Assign each PR to exactly one bucket (checked in this order):

| Bucket | Condition |
|--------|-----------|
| **READY TO MERGE** | `mergeable == "MERGEABLE"` AND all required checks passed AND `reviewDecision` in `("APPROVED", null, "")` |
| **CONFLICTS** | `mergeable == "CONFLICTING"` (regardless of CI state) |
| **FAILING** | `mergeable != "CONFLICTING"` AND any required check has `conclusion == "FAILURE"` or `conclusion == "TIMED_OUT"` |
| **PENDING** | `mergeable != "CONFLICTING"` AND at least one required check is in progress or queued (no failures) |
| **NO CI RUN** | `statusCheckRollup` is empty or null AND not conflicting |

CI status helpers (apply to required checks only — checks where `isRequired == true`):

```python
def required_checks(pr):
    return [c for c in (pr.get("statusCheckRollup") or []) if c.get("isRequired", False)]

def ci_status(pr):
    checks = required_checks(pr)
    if not checks:
        return "no_ci"
    if any(c.get("conclusion") in ("FAILURE", "TIMED_OUT") for c in checks):
        return "failing"
    if any(c.get("status") in ("IN_PROGRESS", "QUEUED", "WAITING", "PENDING") for c in checks):
        return "pending"
    if all(c.get("conclusion") == "SUCCESS" for c in checks):
        return "green"
    return "no_ci"
```

If `mergeable == "UNKNOWN"`, treat as PENDING (GitHub is still computing mergeability).

## Output Format

```
=== Open PRs — OmniNode-ai (2026-02-23) ===

--- READY TO MERGE (2) ---
  omniclaude        #247  jonah/omn-2345-fix-hook-timeout      CI: green    Approved
  omnibase_core     #183  jonah/omn-2290-pydantic-v2-upgrade   CI: green    (no review)

--- FAILING (1) ---
  omniintelligence  #91   jonah/omn-2301-drift-classifier      CI: failing  Approved
      failing checks: quality, test

--- PENDING (3) ---
  omnibase_infra    #134  jonah/omn-2355-kafka-dlq             CI: pending  (no review)
  omnibase_infra    #133  jonah/omn-2340-session-store         CI: pending  (no review)
  omnidash          #47   jonah/omn-2360-analytics-panel       CI: pending  (no review)

--- CONFLICTS (1) ---
  omnibase_spi      #28   jonah/omn-2200-spi-refactor          CI: green    (no review)

--- NO CI RUN (1) ---
  omnimemory        #62   jonah/omn-2290-ingestion-rewrite     CI: none     (no review)

TOTAL: 8 open PRs — 2 ready, 1 failing, 3 pending, 1 conflicts, 1 no CI
```

Column widths:
- Repo name: left-aligned, padded to 18 chars
- PR number: right-aligned, 4 chars (`#247`)
- Branch name: left-aligned, truncated to 45 chars if longer
- CI badge: one of `CI: green`, `CI: failing`, `CI: pending`, `CI: none`
- Review: `Approved`, `Changes requested`, `(no review)`, `Review required`

For FAILING PRs, print a second indented line listing the names of the failing checks
(comma-separated). Limit to the first 5 check names; append `...` if more.

If a bucket is empty, omit its section entirely from the output.

If `--ready-only` is set, only the READY TO MERGE section is printed (plus the summary line).

## Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--repo` | string | (all default repos) | Short name or full slug of a single repo to scan |
| `--ready-only` | bool | false | Print only READY TO MERGE PRs |
| `--include-drafts` | bool | false | Include draft PRs in all buckets |

## Error Handling

| Situation | Action |
|-----------|--------|
| `gh pr list` fails for one repo | Print `  [WARN] <repo>: gh fetch failed — skipping` under that repo section; continue |
| All repos fail | Print error and exit |
| `gh` not authenticated | Print actionable message: `gh auth login` or check `GH_TOKEN` |
| No open PRs found in any repo | Print `No open PRs found across scanned repos.` |

## See Also

- `review-all-prs` skill — runs local-review on every open PR branch (heavy workflow)
- `merge-sweep` skill — merges all READY TO MERGE PRs
- `auto-merge` skill — merges a single PR with a Slack HIGH_RISK gate
- `pr-watch` skill — watches a single PR until CI passes or fails
