---
description: End-of-day close-out pipeline with explicit step ordering and safety constraints. Delegates repo-specific mechanics to existing skills (/merge_sweep, /release, /redeploy, /integration_sweep).
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - close-out
  - pipeline
  - merge
  - release
  - deploy
author: OmniClaude Team
composable: true
---

# close-out

End-of-day close-out pipeline with explicit step ordering and safety constraints.
Delegates repo-specific mechanics to existing skills.

## Constraints

- NEVER serialize independent tracks. Run parallel work in parallel.
- NEVER disable safety rails. Work WITH pre-commit hooks, CI gates, and review requirements.
- NEVER skip the integration-sweep gate. A FAIL or contract UNKNOWN halts the run.

## Steps

### Merge Sweep

Invoke `/merge_sweep` to drain all open PRs with passing CI.

- Run across all active repos in parallel
- Skip PRs with failing CI or unresolved review comments
- Log merged PRs and skipped PRs with reasons

### Integration Sweep (Hard Gate)

Invoke `/integration_sweep` to verify all recently merged work.

- **HALT on any FAIL or contract UNKNOWN** -- do NOT proceed to release
- Continue only on PASS or NOT_APPLICABLE
- If halted: write diagnosis to `docs/diagnosis-close-out-<date>.md` and stop

### Release

Invoke `/release` for each repo that has unreleased changes.

- Release in dependency-tier order (core -> spi -> infra -> others)
- Each repo release is independent after tier ordering
- Verify PyPI publish success before proceeding

### Redeploy

Invoke `/redeploy` to refresh the runtime with new versions.

- Sync bare clones
- Rebuild Docker runtime
- Seed Infisical if contracts changed
- Verify health endpoints respond

### Verification

- Confirm all PRs from Step 1 are merged (not just attempted)
- Confirm all releases from Step 3 have published tags
- Confirm runtime health from Step 4
- Write close-out summary to `docs/tracking/close-out-<date>.md`

## Error Handling

- 3 consecutive step failures -> halt and notify
- Any step failure -> log to friction registry, continue with other repos
- Integration-sweep failure -> hard halt, no exceptions

## Delegation

This skill orchestrates workflow order. It does NOT implement:
- Release mechanics (delegated to `/release`)
- Deployment mechanics (delegated to `/redeploy`)
- PR merging logic (delegated to `/merge_sweep`)
- Integration probes (delegated to `/integration_sweep`)
