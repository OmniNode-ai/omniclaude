---
description: Detect merge-queue head PRs stalled by orphaned third-party check-runs and auto-dequeue+re-enqueue to unwedge downstream PRs
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - merge-queue
  - github
  - autonomous
  - pipeline
  - recovery
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo short-names under OmniNode-ai (default: ONEX_QUEUE_REPOS env or the canonical 9-repo set)"
    required: false
  - name: --dry-run
    description: "Classify candidates and print actions without touching the merge queue"
    required: false
  - name: --awaiting-minutes
    description: "Queue-head AWAITING_CHECKS threshold before a stall is considered (default 30)"
    required: false
  - name: --orphan-minutes
    description: "Minutes a check must sit IN_PROGRESS/null-conclusion before classified orphaned (default 20)"
    required: false
---

# unstick_queue — auto-unwedge merge-queue stalls

## Purpose

GitHub merge queues require ALL `statusCheckRollup` entries to complete — not just the repo's required checks on `main`. Third-party bot check-runs (CodeRabbit, flaky runners, dropped webhooks) can hang `IN_PROGRESS` indefinitely, pinning the queue head `AWAITING_CHECKS` forever and blocking every downstream PR from merging.

This skill detects that specific condition and recovers by dequeuing + re-enqueuing the head PR. It is deliberately scoped to avoid admin-bypass of genuine failures: a PR with a failed *required* check is classified `BROKEN` and left alone.

## Scope

The skill's scope is defined as follows:

1. Probe `repository.mergeQueue.entries` for every repo in scope.
2. For each entry at `position == 1` with `state == AWAITING_CHECKS` longer than `awaiting-minutes` (default 30):
   - Fetch `statusCheckRollup` via GraphQL.
   - Run `plugins/onex/hooks/lib/queue_stall_classifier.classify_queue_entry`.
3. Act on the verdict:
   - `STALL` — dequeue via `dequeuePullRequest`, sleep briefly, re-enqueue via `enqueuePullRequest`. Record the event under `$ONEX_STATE_DIR/queue-unstick/<repo>/pr-<N>.json`.
   - `BROKEN` — skip (real failure; not our problem).
   - `ESCALATE` — same PR was unstuck ≥ 3 times within the past hour; stop auto-healing and emit friction via `/onex:record_friction` so the deeper cause is surfaced.
   - `HEALTHY` — no action.

## Non-goals

- Do NOT admin-bypass check-runs (mark complete, skip).
- Do NOT edit branch-protection required contexts.
- Do NOT close/reopen PRs.

## Invocation

Tick path (preferred): `ai.omninode.unstick-queue.plist` runs every 10 minutes via `scripts/cron-unstick-queue.sh`.

Interactive: `/onex:unstick_queue --dry-run --repos omnibase_infra,omniclaude` for manual inspection.

## Files

- `plugins/onex/hooks/lib/queue_stall_classifier.py` — pure classifier + persistence (tested).
- `scripts/lib/run-unstick-queue.py` — the runner the cron wrapper invokes.
- `scripts/cron-unstick-queue.sh` — headless wrapper + lock + circuit breaker.
- `scripts/launchd/ai.omninode.unstick-queue.plist` — launchd agent (600s interval).

## See Also

- Sibling: `_queue_heal` in `cron-merge-sweep.sh` (handles method-mismatch silent drops — this skill handles check-rollup stalls)
