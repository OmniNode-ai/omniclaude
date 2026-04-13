---
description: Org-wide coordinated release pipeline — bumps versions, pins cross-repo deps, creates PRs, merges, tags, and triggers PyPI publish across all OmniNode repos in dependency-tier order
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - release
  - versioning
  - pypi
  - pipeline
  - cross-repo
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: repos
    description: "Repo names to release (space-separated). Default: all repos in dependency graph"
    required: false
  - name: --all
    description: "Explicitly release all repos in dependency graph"
    required: false
  - name: --bump
    description: "Override bump level: major | minor | patch. Default: inferred from conventional commits"
    required: false
  - name: --dry-run
    description: "Show plan table and exit without making changes"
    required: false
  - name: --resume
    description: "Resume a previously failed run by run_id"
    required: false
  - name: --skip-pypi-wait
    description: "Don't block on PyPI package availability after publish"
    required: false
  - name: --gate-attestation
    description: "Pre-issued gate token for audit trail"
    required: false
  - name: --pypi-timeout-minutes
    description: "Minutes to wait for PyPI package availability after publish (default: 10)"
    required: false
  - name: --run-id
    description: "Explicit run ID for state file naming (default: auto-generated)"
    required: false
  - name: --autonomous
    description: "Skip the HIGH_RISK gate (for automated pipelines); silence NEVER advances the gate"
    required: false
  - name: --require-gate
    description: "Force HIGH_RISK gate even when --autonomous is set"
    required: false
inputs:
  - name: repos
    description: "list[str] — repo names to release; empty = all repos in graph"
  - name: bump_override
    description: "str | None — major | minor | patch; None = infer from commits"
  - name: gate_attestation
    description: "str | None — pre-issued gate token for --gate-attestation mode"
outputs:
  - name: skill_result
    description: "ModelSkillResult with repos_succeeded, repos_failed, run_id"
---

# Release

**Announce at start:** "I'm using the release skill."

## Usage

```
/release omniclaude omnibase_core        # Release specific repos
/release --all --bump patch              # All repos, patch bump
/release --dry-run                       # Show plan, no changes
/release --resume <run_id>               # Resume failed run
/release --gate-attestation <token>      # Pre-issued gate token for audit trail
```

## Execution

### Step 1 — Parse arguments

- `repos` → space-separated repo names (default: full dependency graph)
- `--bump` → version bump level (default: inferred from conventional commits)
- `--dry-run` → show plan table, no writes
- `--resume <run_id>` → resume from failed phase
- `--gate-attestation` → pre-issued gate token for audit trail

### Step 2 — Initialize node (contract verification)

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_release \
  [<repos>...] \
  [--bump <level>] \
  [--dry-run] \
  [--autonomous]
```

Outputs `ModelReleaseStartCommand` JSON. Note: handler is a structural placeholder;
full migration tracked in OMN-8004.

### Step 3 — Execute release phases

Processes repos in dependency-tier order (tier 0 → tier N):

1. **GATE**: Validate gate attestation (if provided) or proceed automatically
2. **BUMP**: For each repo — infer or apply version bump; update `pyproject.toml` + `__version__`
3. **PIN**: Update cross-repo dependency pins in downstream repos
4. **PR**: Create release PR per repo via `gh pr create`; enable auto-merge
5. **MERGE**: Wait for CI + merge queue; confirm merged
6. **TAG**: `git tag v{version}` + push; trigger PyPI publish workflow
7. **WAIT**: Poll PyPI for package availability (unless `--skip-pypi-wait`)
8. **VERIFY**: Confirm installed version matches released version

### Step 4 — Report

Display release table: repo, old version, new version, PR, tag, PyPI status.
Write `ModelSkillResult` to `$ONEX_STATE_DIR/skill-results/{context_id}/release.json`.

## Safety

- Proceeds automatically — no Slack approval gate
- `--dry-run` produces zero side effects: no bumps, PRs, tags, or PyPI triggers
- Resume support: state written after each phase; `--resume <run_id>` skips completed phases
- Cross-repo dependency pins use exact ==X.Y.Z format for determinism (exact pin policy)

## Dependency Graph

Repos are released in dependency-tier order to guarantee downstream consumers get updated pins:

| Tier | Repos |
|------|-------|
| Tier 1 | omnibase_spi |
| Tier 2 | omnibase_core, omnibase_compat |
| Tier 3 | omniclaude, omniintelligence, omnimemory, omnimarket |
| Tier 4 | omninode_infra, omnidash |

Tier N+1 repos pin the released version of Tier N repos. If a Tier 2 release fails,
Tier 3 and Tier 4 are BLOCKED.

## Error Table

| Error Code | Condition | Behavior |
|------------|-----------|----------|
| GRAPH_DRIFT | Dependency graph differs from last snapshot | Abort and report |
| NOTHING_TO_RELEASE | No version bump inferred from commits | Skip repo (not an error) |
| LINT_FAILED | ruff/mypy CI gate fails | TIER_BLOCKED for downstream |
| PYPI_TIMEOUT | Package not available on PyPI after timeout | Mark as PARTIAL |
| TIER_BLOCKED | Upstream tier failed | Skip repo, continue with others |
| GATE_REJECTED | Gate attestation invalid | Abort entire release |

## ModelSkillResult

```python
class ModelSkillResult:
    status: Literal["SUCCESS", "PARTIAL", "FAILED", "DRY_RUN"]
    repos_succeeded: list[str]
    repos_failed: list[str]
    run_id: str
```

## Phase State Machine

Each repo progresses through this phase state machine independently:

```
PLANNED → WORKTREE → BUMPED → PINNED → CHANGELOG → LOCKED
       → LINT → COMMITTED → PUSHED → PR_CREATED → MERGED
       → TAGGED → PUBLISHED → DONE
```

Phases: PLANNED, WORKTREE, BUMPED, PINNED, CHANGELOG, LOCKED, LINT, COMMITTED,
PUSHED, PR_CREATED, MERGED, TAGGED, PUBLISHED, DONE.

State is written atomically after each transition using a temp file + rename
to guarantee crash-safe resume.

## Idempotency

All mutations are deduplicated on resume:

| Operation | Idempotency Key |
|-----------|----------------|
| PR dedupe | Check `gh pr list --head <branch>` before creating |
| Tag dedupe | Check `git tag -l <version>` before tagging |
| Worktree reuse | Reuse existing worktree at `$OMNI_HOME/worktrees/<run_id>/<repo>` |

## Cross References

- **merge-sweep**: Used to verify merges succeeded and queues are clear
- **pr-safety**: Validates PR is mergeable (no conflicts, no blocking reviews)
- **release.yml**: GitHub Action triggered post-merge for PyPI publish
- **auto-tag-reusable**: Reusable workflow for git tag + push

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_release/ (structural placeholder)
contract   -> node_release/contract.yaml
migration  -> OMN-8004 (full handler implementation)
```
