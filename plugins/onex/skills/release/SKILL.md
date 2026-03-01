---
name: release
description: Org-wide coordinated release pipeline — bumps versions, pins cross-repo deps, creates PRs, merges, tags, and triggers PyPI publish across all OmniNode repos in dependency-tier order
version: 1.0.0
category: workflow
tags:
  - release
  - versioning
  - pypi
  - pipeline
  - cross-repo
  - high-risk
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: repos
    description: "Repo names to release (positional, space-separated). Default: all repos in dependency graph"
    required: false
  - name: --all
    description: "Explicitly release all repos in dependency graph (equivalent to omitting repos)"
    required: false
  - name: --bump
    description: "Override bump level for all repos: major | minor | patch. Default: inferred from conventional commits"
    required: false
  - name: --dry-run
    description: "Show plan table and exit without making any changes. Zero side effects."
    required: false
  - name: --resume
    description: "Resume a previously failed run. Value: <run_id> from a prior state file"
    required: false
  - name: --skip-pypi-wait
    description: "Don't block on PyPI package availability after publish trigger"
    required: false
  - name: --pypi-timeout-minutes
    description: "Max minutes to wait for PyPI propagation per repo (default: 10)"
    required: false
  - name: --run-id
    description: "Override the auto-generated run ID. Useful for deterministic testing."
    required: false
  - name: --gate-attestation
    description: "Pre-issued gate token to bypass Slack HIGH_RISK gate (format: <slack_ts>:<run_id>)"
    required: false
inputs:
  - name: repos
    description: "list[str] — repo names to release; empty list means all repos in graph"
  - name: bump_override
    description: "str | None — major | minor | patch; None means infer from commits"
  - name: gate_attestation
    description: "str | None — pre-issued gate token for --gate-attestation mode"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: SUCCESS | PARTIAL | FAILED | DRY_RUN"
---

# Release

## Overview

Composable skill that orchestrates a coordinated multi-repo release across the entire OmniNode
package ecosystem. Repos are released in strict dependency-tier order to ensure that downstream
packages can pin exact versions of their upstream dependencies.

**Announce at start:** "I'm using the release skill."

**SAFETY INVARIANT**: Release is a HIGH_RISK action. Silence is NEVER consent for
the gate. Explicit approval required unless `--gate-attestation=<token>` is passed with a
valid pre-issued token.

## Quick Start

```
/release                                          # Release all repos (infer bumps)
/release --dry-run                                # Show plan, don't execute
/release omnibase_core omnibase_infra             # Release specific repos only
/release --bump minor                             # Force minor bump for all
/release --resume release-20260225-a3f7b2         # Resume a failed run
/release --skip-pypi-wait                         # Don't wait for PyPI propagation
/release --gate-attestation=1740312612.000100:release-20260225-a3f7b2  # Bypass gate
```

## Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `repos` | `list[str]` | all | Repo names to release (positional, space-separated) |
| `--all` | flag | — | Explicitly release all repos in dependency graph |
| `--bump` | `major\|minor\|patch` | inferred | Override bump level for all repos |
| `--dry-run` | flag | false | Show plan table and exit; zero side effects |
| `--resume` | `<run_id>` | — | Resume a previously failed run from its state file |
| `--skip-pypi-wait` | flag | false | Don't block on PyPI availability after publish |
| `--pypi-timeout-minutes` | int | 10 | Max minutes to wait for PyPI propagation per repo |
| `--run-id` | string | auto | Override the auto-generated run ID |
| `--gate-attestation` | `<slack_ts>:<run_id>` | — | Pre-issued gate token to bypass Slack HIGH_RISK gate |

## Dependency Graph (Tier Order)

Repos are released in strict tier order. Within a tier, repos are released sequentially
(not in parallel) to avoid race conditions on shared CI runners.

```
Tier 1: omnibase_spi          (no internal deps)
Tier 2: omnibase_core         (depends on: omnibase_spi)
Tier 3: omnibase_infra        (depends on: omnibase_core, omnibase_spi)
         omniintelligence      (depends on: omnibase_core, omnibase_spi)
         omnimemory            (depends on: omnibase_core, omnibase_spi)
Tier 4: omniclaude            (depends on: omnibase_core, omnibase_infra, omniintelligence)
```

**Drift guard**: Before execution, the skill verifies that every repo in `omni_home` that
declares a `pyproject.toml` with OmniNode dependencies is present in the tier graph. If a
repo is found that is not in the graph, the skill fails immediately with `GRAPH_DRIFT`.

### Tier Execution Rule

A tier N repo is only released after ALL tier N-1 repos have completed (including tag push
and optional PyPI availability confirmation). This ensures that when a tier N repo pins
`omnibase_core==X.Y.Z`, that version is actually published and installable.

## Execution Algorithm

```
1. VALIDATE
   - If --gate-attestation is set and token format is invalid → error immediately
   - If --resume is set → load state file, validate run_id, skip to resume point

2. SCAN (sequential, per tier order):
   For each repo:
     a. Find last git tag matching <repo>/vX.Y.Z pattern
     b. Count commits since last tag
     c. Infer bump level from conventional commit prefixes:
        - feat:     → minor
        - fix:      → patch
        - BREAKING CHANGE / feat!: / fix!: → major
        - No unreleased commits → skip (NOTHING_TO_RELEASE for this repo)
     d. Apply --bump override if set (overrides inference for all repos)
     e. Compute new version

3. DRIFT GUARD:
   Compare scanned repo set against hardcoded tier graph.
   If mismatch → fail with GRAPH_DRIFT error, print expected vs actual

4. PLAN DISPLAY:
   Render table:
     repo | tier | current | new | bump | commits | status
   Compute plan_hash = SHA256(JSON(plan))

5. If --dry-run: print table, emit ModelSkillResult(status=DRY_RUN), exit

6. GATE:
   If --gate-attestation=<token>:
     Validate token format, use for audit trail
   Else:
     Post HIGH_RISK Slack gate with plan table + plan_hash
     Invoke slack_gate_poll.py to poll for reply
     Parse reply (approve / reject)
     If rejected or timeout: emit ModelSkillResult(status=FAILED), exit

7. EXECUTE (sequential tiers, sequential repos within tier):
   For each tier (1 → 4):
     For each repo in tier:
       Execute 12 sub-steps (see Per-Repo Release Sub-Steps below)
       Update state file after each sub-step (atomic write)
       On failure: mark repo as FAILED, halt remaining repos in this tier + all later tiers

8. CLEANUP:
   Remove worktrees
   Archive state file to ~/.claude/state/release/archive/

9. SUMMARY:
   Print summary table: repo | old → new | PR | tag | PyPI
   Post summary to Slack (LOW_RISK, informational)

10. EMIT ModelSkillResult
```

## Per-Repo Release Sub-Steps

Each repo goes through 12 sequential sub-steps. State is persisted after each sub-step
for resume support.

| Step | Name | Description |
|------|------|-------------|
| 1 | WORKTREE | Create worktree at `omni_worktrees/release/<run_id>/<repo>/` on branch `release/<run_id>/<repo>` |
| 2 | BUMP | Update `version` field in `pyproject.toml` to new version |
| 3 | PIN | Update dependency pins in `pyproject.toml` to `==X.Y.Z` for any same-run deps that have already completed |
| 4 | CHANGELOG | Generate CHANGELOG entry from conventional commits since last tag |
| 5 | LOCK | Run `uv lock` to regenerate lockfile with new version + pins |
| 6 | LINT | Run `pre-commit run --all-files`; fail repo on hook failure |
| 7 | COMMIT | `git commit -am "release: <repo> vX.Y.Z [OMN-XXXX]"` |
| 8 | PUSH | Push branch via `_lib/pr-safety/safe_push()` to `origin release/<run_id>/<repo>` |
| 9 | PR | Create PR via `gh pr create` (dedupe check first); reference `pr-safety` helpers |
| 10 | MERGE | Merge PR via `gh pr merge --squash` (reference `auto-merge` sub-skill) |
| 11 | TAG | Create and push tag `<repo>/vX.Y.Z` (dedupe check: skip if tag exists) |
| 12 | PUBLISH | Trigger `release.yml` / `auto-tag-reusable.yml` GitHub Action; optionally wait for PyPI availability |

### Pin Policy

**MVP**: Exact pins only (`==X.Y.Z`). When a tier N repo depends on a tier N-1 repo
that was released in the same run, the dependency specifier is updated to `==<new_version>`.

Example: If `omnibase_core` was bumped to `1.5.0` in this run, then `omnibase_infra`'s
`pyproject.toml` dependency on `omnibase_core` becomes `omnibase_core==1.5.0`.

## ModelSkillResult

Written to `~/.claude/skill-results/<context_id>/release.json`:

```json
{
  "skill": "release",
  "status": "SUCCESS | PARTIAL | FAILED | DRY_RUN",
  "run_id": "release-20260225-a3f7b2",
  "gate_token": "<slack_ts>:<run_id>",
  "plan_hash": "sha256:abc123...",
  "repos_attempted": 6,
  "repos_succeeded": 5,
  "repos_failed": 1,
  "repos_skipped": 0,
  "details": [
    {
      "repo": "omnibase_spi",
      "tier": 1,
      "old_version": "1.2.0",
      "new_version": "1.2.1",
      "bump": "patch",
      "commits_since_tag": 3,
      "pr_url": "https://github.com/OmniNode-ai/omnibase_spi/pull/42",
      "pr_number": 42,
      "tag": "omnibase_spi/v1.2.1",
      "pypi_status": "available | pending | skipped | failed",
      "phase": "DONE",
      "error": null
    },
    {
      "repo": "omnibase_infra",
      "tier": 3,
      "old_version": "2.0.0",
      "new_version": "2.1.0",
      "bump": "minor",
      "commits_since_tag": 12,
      "pr_url": null,
      "pr_number": null,
      "tag": null,
      "pypi_status": null,
      "phase": "LINT",
      "error": "Pre-commit hook failed: ruff found 3 errors"
    }
  ]
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `SUCCESS` | All targeted repos released successfully |
| `PARTIAL` | Some repos released, some failed; released repos are tagged and published |
| `FAILED` | Unrecoverable error before any repo completed (gate rejected, graph drift, etc.) |
| `DRY_RUN` | Plan displayed, no changes made |

## State Model

### Run ID Generation

```
run_id = "release-<YYYYMMDD>-<short_hash>"

where short_hash = sha256(sorted_repo_names + date)[:6]
```

The run ID is deterministic given the same repo set and date, enabling idempotent resume.
Use `--run-id` to override for testing.

### State File

**Path**: `~/.claude/state/release/<run_id>.json`

```json
{
  "run_id": "release-20260225-a3f7b2",
  "started_at": "2026-02-25T14:00:00Z",
  "updated_at": "2026-02-25T14:15:00Z",
  "plan_hash": "sha256:abc123...",
  "gate_token": "<slack_ts>:<run_id>",
  "status": "in_progress | completed | failed | partial",
  "repos": {
    "omnibase_spi": {
      "tier": 1,
      "old_version": "1.2.0",
      "new_version": "1.2.1",
      "bump": "patch",
      "phase": "DONE",
      "phase_history": [
        {"phase": "PLANNED", "at": "2026-02-25T14:00:00Z"},
        {"phase": "WORKTREE", "at": "2026-02-25T14:01:00Z"},
        {"phase": "DONE", "at": "2026-02-25T14:05:00Z"}
      ],
      "worktree_path": "/Volumes/PRO-G40/Code/omni_worktrees/release/release-20260225-a3f7b2/omnibase_spi",  # local-path-ok
      "branch": "release/release-20260225-a3f7b2/omnibase_spi",
      "pr_url": "https://github.com/OmniNode-ai/omnibase_spi/pull/42",
      "pr_number": 42,
      "tag": "omnibase_spi/v1.2.1",
      "error": null
    }
  }
}
```

### Phase State Machine

Each repo transitions through phases in strict order. No phase may be skipped except via
resume (which re-enters at the last incomplete phase).

```
PLANNED → WORKTREE → BUMPED → PINNED → CHANGELOG → LOCKED → LINT → COMMITTED → PUSHED → PR_CREATED → MERGED → TAGGED → PUBLISHED → DONE
```

**Phase transition rules**:
- Forward-only: a repo never moves backwards in the state machine
- On failure: phase is set to the failing phase, `error` is populated
- On resume: execution restarts from the failing phase (not from PLANNED)
- DONE is terminal: a repo in DONE is never re-processed

### Resume Semantics

When invoked with `--resume <run_id>`:

1. Load state file from `~/.claude/state/release/<run_id>.json`
2. Validate run_id matches
3. For each repo in tier order:
   - If phase == `DONE`: skip entirely
   - If phase == any other value: restart from that phase
   - If phase == `PLANNED`: start fresh (first run or pre-scan failure)
4. Re-display the plan table (with completed repos marked)
5. Re-post Slack gate (unless `--gate-attestation` provided)
6. Execute remaining work

**Resume does NOT re-run completed phases.** If `omnibase_spi` is in `DONE` state, it
will not be re-scanned, re-bumped, or re-tagged. The state file is the source of truth.

### Atomic Writes

State file updates use the write-to-temp-then-rename pattern:

```python
import json, os, tempfile

def atomic_write_state(state: dict, path: str) -> None:
    """Write state file atomically to prevent corruption on crash."""
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
```

This ensures that a crash mid-write never produces a corrupt state file. The previous
state file is always either the old version or the new version, never a partial write.

## Idempotency Keys

Every mutation has a corresponding idempotency check to make resume safe:

| Mutation | Idempotency Key | Check |
|----------|----------------|-------|
| Create worktree | `release/<run_id>/<repo>` branch + path | If worktree path exists and branch matches, reuse |
| Version bump | `pyproject.toml` version field | If version already matches target, skip |
| Dependency pin | `pyproject.toml` dependency specifier | If pin already matches `==X.Y.Z`, skip |
| CHANGELOG entry | Entry header with version string | If entry for version exists, skip |
| uv lock | `uv.lock` content hash | Always re-run (cheap, ensures consistency) |
| Pre-commit | Pre-commit output | Always re-run (cheap, ensures clean state) |
| Git commit | Branch HEAD content | If HEAD message matches `release: <repo> vX.Y.Z`, skip |
| Git push | Remote branch state | If remote branch exists and matches local HEAD, skip |
| PR creation | Open PR with matching branch | `gh pr list --head <branch>` — if PR exists, reuse |
| PR merge | PR state | If PR is already merged, skip |
| Tag creation | Tag existence | `git tag -l <tag>` — if tag exists, skip push |
| PyPI publish | GitHub Action trigger | Trigger is idempotent (re-trigger is safe); PyPI rejects duplicate versions |

### Branch Naming Convention

```
release/<run_id>/<repo>

Example: release/release-20260225-a3f7b2/omnibase_core
```

This naming:
- Prevents collision with feature branches
- Encodes the run_id for audit trail
- Allows worktree reuse on resume (same branch name = same worktree)

### Run Marker

- State file existence at `~/.claude/state/release/<run_id>.json` = run in progress
- On successful completion: state file moved to `~/.claude/state/release/archive/<run_id>.json`
- On `--resume`: state file remains in active location until completion
- Stale runs: if a state file is older than 24 hours and status is not `completed`, it
  is considered stale. A new run for the same repos will warn but proceed (with a new run_id).

## Error Table

| Error | Code | Behavior | Recovery |
|-------|------|----------|----------|
| Graph drift (repo in omni_home not in tier graph) | `GRAPH_DRIFT` | Fail immediately, print expected vs actual repo set | Update tier graph in SKILL.md and prompt.md |
| No unreleased commits for a repo | `NOTHING_TO_RELEASE` | Skip repo (not an error); reduce from plan | None needed |
| Worktree already exists (wrong branch) | `WORKTREE_CONFLICT` | Fail repo; do not clobber existing worktree | Manually remove conflicting worktree |
| Worktree dirty (uncommitted changes) | `WORKTREE_DIRTY` | Fail repo; do not proceed with dirty state | Clean or remove worktree, then `--resume` |
| Pre-commit hook failure | `LINT_FAILED` | Fail repo; remaining repos in same tier + later tiers blocked | Fix lint issues, then `--resume` |
| `uv lock` failure | `LOCK_FAILED` | Fail repo; dependency resolution error | Fix dependency conflicts, then `--resume` |
| PR creation failure | `PR_FAILED` | Fail repo; GitHub API error or branch protection issue | Check GitHub permissions, then `--resume` |
| PR merge failure | `MERGE_FAILED` | Fail repo; merge conflict or CI failure on PR | Resolve conflict or fix CI, then `--resume` |
| Tag already exists (different commit) | `TAG_CONFLICT` | Fail repo; tag points to different commit than expected | Delete stale tag manually, then `--resume` |
| PyPI timeout | `PYPI_TIMEOUT` | Fail repo; package not available after `--pypi-timeout-minutes` | Check PyPI status, then `--resume` or `--skip-pypi-wait` |
| Mid-chain failure | `TIER_BLOCKED` | Remaining repos in current tier + all later tiers marked `BLOCKED` | Fix failing repo, then `--resume` |
| Gate rejected | `GATE_REJECTED` | Fail entire run; no repos modified | Re-run with corrected plan |
| Gate timeout | `GATE_TIMEOUT` | Fail entire run; silence never advances HIGH_RISK | Re-run or provide `--gate-attestation` |
| Invalid `--gate-attestation` format | `INVALID_GATE_TOKEN` | Fail immediately; do not scan or execute | Provide valid token |
| State file corrupt / unparseable | `STATE_CORRUPT` | Fail immediately; cannot resume | Delete state file and start fresh run |
| State file not found (with `--resume`) | `STATE_NOT_FOUND` | Fail immediately; nothing to resume | Start fresh run without `--resume` |

## Slack Gate Message Format

```
[HIGH_RISK] release — coordinated release of N repos

Run: <run_id>
Plan Hash: <plan_hash>

RELEASE PLAN:
  Tier 1:
    omnibase_spi       1.2.0 → 1.2.1  (patch, 3 commits)
  Tier 2:
    omnibase_core      1.4.0 → 1.5.0  (minor, 8 commits)
  Tier 3:
    omnibase_infra     2.0.0 → 2.1.0  (minor, 12 commits)
    omniintelligence   0.9.0 → 0.9.1  (patch, 2 commits)
    omnimemory         0.3.0 → 0.3.1  (patch, 1 commit)
  Tier 4:
    omniclaude         0.3.0 → 0.4.0  (minor, 15 commits)

SKIPPED (no unreleased commits):
  (none)

Commands:
  approve            — execute full release plan
  reject             — cancel entire release

This is HIGH_RISK — silence will NOT auto-advance.
```

## Credential Resolution

| Credential | Source | Purpose |
|------------|--------|---------|
| `SLACK_BOT_TOKEN` | `~/.omnibase/.env` | Slack gate posting |
| `SLACK_CHANNEL_ID` | `~/.omnibase/.env` | Slack channel target |
| `GITHUB_TOKEN` | `gh auth status` | PR creation, merge, tag push |
| `PYPI_TOKEN` | GitHub Actions secrets | PyPI publish (via release.yml) |

## Sub-skills Used

- `slack-gate` (v2.0.0, OMN-2627) — HIGH_RISK gate with `chat.postMessage` + reply polling
- `slack_gate_poll.py` — reply polling helper (part of `slack-gate` skill)
- `pr-safety` helpers — PR creation guards and claim checks
- `auto-merge` — PR merge execution (referenced for merge strategy)
- `merge-sweep` — merge readiness predicate (referenced for merge checks)

## Cross-references

| Reference | Purpose |
|-----------|---------|
| `skills/merge-sweep/SKILL.md` | PR merge readiness predicate, merge method |
| `skills/_lib/pr-safety/helpers.md` | PR creation guards, claim checks |
| `.github/workflows/release.yml` | PyPI publish trigger (per-repo) |
| `.github/workflows/auto-tag-reusable.yml` | Tag-based release flow |
| `skills/slack-gate/` | HIGH_RISK gate implementation |

## Changelog

- **v1.0.0** (OMN-2805): Initial interface definition — arguments, dependency graph, error
  table, ModelSkillResult schema, state model, idempotency keys.

## See Also

- `merge-sweep` skill — PR merge orchestration
- `auto-merge` skill — single-PR merge execution
- `slack-gate` skill — HIGH_RISK gate implementation
- `pr-safety` helpers — PR creation and mutation guards
- OMN-2805 — this ticket (interface definition)
- OMN-2806 — prompt.md orchestration logic
- OMN-2807 — node shell scaffold
- OMN-2808 — verification and testing
