---
name: fix-prs
description: Org-wide PR repair — scans all repos for broken PRs and autonomously fixes merge conflicts, failing CI, and unaddressed review comments
version: 1.0.0
category: workflow
tags:
  - pr
  - github
  - repair
  - autonomous
  - pipeline
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all repos in omni_home)
    required: false
  - name: --category
    description: "Failure categories to address: conflicts | ci | reviews | all (default: all)"
    required: false
  - name: --max-total-prs
    description: Hard cap on PRs processed per run (default: 20)
    required: false
  - name: --max-parallel-prs
    description: Concurrent fix agents (default: 5)
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel (default: 3)
    required: false
  - name: --max-fix-iterations
    description: Max ci-failures iterations per PR (default: 3)
    required: false
  - name: --authors
    description: Limit to PRs by these GitHub usernames (comma-separated; default: all)
    required: false
  - name: --allow-force-push
    description: Permit force-push after rebase; always leaves a PR comment explaining push (default: false)
    required: false
  - name: --ignore-ledger
    description: Bypass idempotency ledger and retry all PRs regardless of prior results (default: false)
    required: false
  - name: --run-id
    description: "Pipeline run ID for claim registry ownership + ledger namespacing. Generated if not provided."
    required: false
  - name: --dry-run
    description: Zero filesystem writes — no claim files, no ledger updates, no PR mutations (default: false)
    required: false
inputs:
  - name: repos
    description: "list[str] — repo names to scan; empty list means all"
  - name: run_id
    description: "str | None — parent pipeline run_id for claim registry + ledger namespacing"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: all_fixed | partial | nothing_to_fix | error"
---

# Fix PRs

## Overview

Fully autonomous skill that scans all open PRs across `omni_home` repos and repairs each one.
Three failure categories are processed in priority order per PR: merge conflicts, failing CI,
unaddressed review comments. No Slack gate — runs to completion autonomously.

**Supersedes**: OMN-2400 (`ci-fix-pipeline` Node) — this skill is a superset.

**Announce at start:** "I'm using the fix-prs skill."

## Failure Category Priority (per PR)

Processed in this order. A PR may have multiple issues; all applicable categories run:

1. **Merge conflicts** — rebase onto `pr.baseRefName` (NEVER hardcoded `main`); must resolve before CI can run reliably
2. **Failing CI** — invoke `ci-failures` sub-skill; skip checks requiring external secrets/infra
3. **Review comments** — invoke `pr-review-dev`; never auto-dismiss reviews, never force-push unless `--allow-force-push`

## PR Classification Predicates

```python
def needs_conflict_work(pr) -> bool:
    return pr["mergeable"] == "CONFLICTING"

def needs_ci_work(pr) -> bool:
    return not is_green(pr)  # any REQUIRED check not SUCCESS

def needs_review_work(pr) -> bool:
    return pr.get("reviewDecision") == "CHANGES_REQUESTED"

def is_green(pr) -> bool:
    required = [c for c in pr["statusCheckRollup"] if c.get("isRequired", False)]
    if not required:
        return True
    return all(c.get("conclusion") == "SUCCESS" for c in required)

def is_merge_ready(pr) -> bool:
    return (
        pr["mergeable"] == "MERGEABLE"
        and is_green(pr)
        and pr.get("reviewDecision") in ("APPROVED", None)
    )

def pr_state_unknown(pr) -> bool:
    return pr["mergeable"] == "UNKNOWN"
```

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--repos` | all | Comma-separated repo names to scan |
| `--category` | `all` | `conflicts` \| `ci` \| `reviews` \| `all` |
| `--max-total-prs` | 20 | Hard cap on PRs processed per run |
| `--max-parallel-prs` | 5 | Concurrent fix agents |
| `--max-parallel-repos` | 3 | Repos scanned in parallel |
| `--max-fix-iterations` | 3 | Max ci-failures sub-skill iterations per PR |
| `--authors` | all | Limit to PRs by these GitHub usernames (comma-separated) |
| `--allow-force-push` | false | Permit force-push after rebase; always leaves PR comment |
| `--ignore-ledger` | false | Bypass idempotency ledger |
| `--run-id` | generated | Pipeline run ID for claim registry ownership + ledger namespacing |
| `--dry-run` | false | Zero filesystem writes — no claim files, no ledger updates, no PR mutations |

## Idempotency Ledger

Per-run record at `~/.claude/pr-queue/<date>/run_<run_id>.json`:

```json
{
  "OmniNode-ai/omniclaude#247": {
    "head_sha": "cbca770e",
    "last_error_fingerprint": "SHA256(phase|error_class|check_name|first_error_line)",
    "last_result": "fixed",
    "retry_count": 1
  }
}
```

**Retry policy**: retry a PR only if `head_sha` changed OR `last_error_fingerprint` differs.
If `retry_count >= 3` and neither condition is met: skip with `result: needs_human`.

**`--ignore-ledger`**: bypass all ledger checks and retry every PR.

## Execution Algorithm

```
1. SCAN (parallel, up to --max-parallel-repos):
   gh pr list per repo, classify each PR:
   - is_merge_ready() → skip (merge-sweep handles these)
   - pr_state_unknown() → skip with warning
   - needs_conflict_work() OR needs_ci_work() OR needs_review_work() → add to work_queue[]

   Apply --authors filter
   Apply --category filter (skip categories not in --category)
   Check ledger: skip PRs where retry_count >= 3 AND head_sha + fingerprint unchanged
   Apply --max-total-prs cap to work_queue[]

2. If work_queue is empty: emit ModelSkillResult(status=nothing_to_fix), exit

3. DISPATCH parallel agents (up to --max-parallel-prs), one per PR:

   For each PR:

   a. IF needs_conflict_work AND --category includes conflicts:
      git fetch origin <pr.baseRefName>
      git rebase origin/<pr.baseRefName>   ← pr.baseRefName, NOT "main"
      Resolve conflicts in each file; git rebase --continue
      git push --force-with-lease (or git push if no rebase happened)
      Post PR comment: "Resolved merge conflict via rebase onto <baseRefName>"
      On rebase failure: record result=failed, reason=conflict_unresolved, skip to next PR

   b. IF conflict was resolved in step a: RE-QUERY GitHub state
      Wait up to 30s for GitHub to compute mergeable state after push
      Re-classify PR with fresh state from gh pr view
      If is_merge_ready() now: record result=fixed, reason=resolved_by_rebase, skip to c/d

   c. IF needs_ci_work AND --category includes ci:
      Query failing checks:
        For each REQUIRED failed check:
          If check name contains external secret indicators (AWS_, DEPLOY_, PROD_, service-account):
            → record result=blocked_external, blocked_check=<name>, skip ci-failures for this check
        If all failing checks are external: record result=blocked_external for PR, skip to d
      Invoke: Skill(skill="onex:ci-failures") with --max-fix-iterations <max_fix_iterations>
      Collect result; record in ledger with new error_fingerprint

   d. IF needs_review_work AND CI is now green AND --category includes reviews:
      Invoke: Skill(skill="onex:pr-review-dev")
      Guardrails:
        - No auto-dismiss of reviews (never use gh api to dismiss)
        - No force-push unless --allow-force-push is set
        - Always post PR comment summarizing changes made
      Collect result

4. COLLECT results from all agents
5. UPDATE ledger (head_sha, last_error_fingerprint, retry_count++)
6. EMIT ModelSkillResult
```

## CI Secrets Guard

Before invoking `ci-failures` for any failing check, inspect the check name:

```
External infra indicators (skip ci-failures for these checks):
  - Check name contains: deploy, production, prod, staging, aws, gcp, azure,
    service-account, docker-push, publish, release, upload-to

If the failing check matches any indicator:
  → record blocked_check = <check_name>
  → result = blocked_external for that check
  → do NOT invoke ci-failures
  → continue to next check
```

If ALL failing checks are blocked_external: record PR as `result: blocked_external`, skip ci-failures entirely.

## Force Push Guardrail

```
--allow-force-push = false (default):
  After rebase: use git push --force-with-lease
  If push requires force (not just lease): post PR comment explaining why, then push

--allow-force-push = true:
  After rebase: use git push --force-with-lease
  Always post PR comment: "Force-pushed after rebase onto <baseRefName> to resolve conflicts"
```

## ModelSkillResult

Written to `~/.claude/pr-queue/<date>/fix-prs_<run_id>.json`:

```json
{
  "skill": "fix-prs",
  "status": "all_fixed | partial | nothing_to_fix | error",
  "run_id": "<run_id>",
  "prs_scanned": 15,
  "prs_processed": 8,
  "prs_fixed": 5,
  "prs_partial": 2,
  "prs_failed": 1,
  "prs_needs_human": 1,
  "prs_blocked_external": 2,
  "prs_skipped_ledger": 1,
  "details": [
    {
      "repo": "OmniNode-ai/omniclaude",
      "pr": 123,
      "head_sha": "abc123",
      "result": "fixed | partial | failed | needs_human | blocked_external | skipped",
      "phases": {
        "conflicts": "resolved | skipped | failed | not_needed",
        "ci": "fixed | blocked_external | failed | skipped | not_needed",
        "reviews": "addressed | skipped | failed | not_needed"
      },
      "blocked_check": null,
      "skip_reason": null
    }
  ]
}
```

Status values:
- `all_fixed` — every work_queue PR resolved
- `partial` — some fixed, some remain (partial|failed|needs_human|blocked_external)
- `nothing_to_fix` — all PRs are merge-ready or unknown-state
- `error` — scan failed or unrecoverable error

## Failure Handling

| Error | Behavior |
|-------|----------|
| Rebase fails with unresolvable conflicts | Record `result: failed`, `reason: conflict_unresolved` |
| CI check requires external secrets | Record `blocked_external`, skip ci-failures for that check |
| `ci-failures` skill fails | Record `result: partial` or `failed`, continue other PRs |
| `pr-review-dev` fails | Record `result: partial`, continue other PRs |
| `gh pr list` fails for a repo | Log warning, skip that repo |
| PR retry_count >= 3, no progress | Record `result: needs_human` |

## Sub-skills Used

- `ci-failures` (existing) — diagnose and fix CI failures per PR
- `pr-review-dev` (existing) — address GitHub review comments

## Integration Test

Integration tests are in `tests/integration/skills/fix_prs/test_fix_prs_integration.py` (OMN-2636).
All tests are static analysis / structural tests — no live GitHub access or external credentials required.

Run with: `uv run pytest tests/integration/skills/fix_prs/ -m unit -v`

### Test Coverage

| Test Case | Description | Marker |
|-----------|-------------|--------|
| Dry-run contract | `nothing_to_fix` exit documented; idempotency ledger documented | unit |
| Claim lifecycle | `acquire_claim` / `release_claim` / heartbeat in `_lib/pr-safety/helpers.md` | unit |
| Claim expiry | Stale claim detection documented in helpers | unit |
| ClaimNotHeldError | Error class documented for mutation guard | unit |
| mutate_pr claim check | `mutate_pr()` asserts claim held before mutation | unit |
| Boundary validation | `boundary_validate()` + `BoundaryViolationError` in helpers | unit |
| Import boundary coverage | `repo_class` parameter enforces app/ui/infra separation | unit |
| CI secrets guard | External infra check skip documented (boundary enforcement) | unit |
| Inventory/ledger consumption | Per-run ledger structure + retry policy documented | unit |
| Ledger check before dispatch | prompt.md references ledger before fix dispatch | unit |
| Max-total-prs cap | Blast radius cap documented | unit |
| TERMINAL_STOP_REASONS defined | All 14 canonical reasons present in helpers | unit |
| ledger_set_stop_reason | Function documented and enforces terminal reason set | unit |
| No direct gh pr merge | fix-prs repairs PRs, does not merge them | unit |
| No direct gh pr checkout | prompt.md delegates checkout to sub-skills | unit |
| No direct worktree creation | Use get_worktree() from _lib/pr-safety | unit |
| Delegates to ci-failures | CI fixing dispatched to ci-failures sub-skill | unit |
| Delegates to pr-review-dev | Review fixing dispatched to pr-review-dev sub-skill | unit |
| ModelSkillResult statuses | all_fixed / partial / nothing_to_fix / error documented | unit |
| Force push guardrail | --allow-force-push + PR comment requirement documented | unit |
| force-with-lease usage | prompt.md uses --force-with-lease, not bare --force | unit |
| baseRefName for rebase | Dynamic base ref (not hardcoded 'main') documented | unit |

## See Also

- `merge-sweep` skill — merges PRs that are already fix-prs clean
- `pr-queue-pipeline` skill — orchestrates fix-prs → merge-sweep in sequence
- `ci-failures` skill — per-PR CI failure analysis and repair
- `pr-review-dev` skill — address code review comments
- OMN-2636 — integration test suite
