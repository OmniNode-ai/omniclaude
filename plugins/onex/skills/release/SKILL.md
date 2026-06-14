---
description: Org-wide coordinated release pipeline (STRUCTURAL PLACEHOLDER — node_release performs no git/gh/PyPI I/O today; full handler implementation tracked in OMN-8004). Target design bumps versions, pins cross-repo deps, creates PRs, merges, tags, and triggers PyPI publish across all OmniNode repos in dependency-tier order
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

> ## ⚠️ Implementation status: STRUCTURAL PLACEHOLDER
>
> **The routed node (`node_release`) performs NO git, `gh`, `uv`, or PyPI I/O today.**
> It is a pure in-memory FSM bookkeeper: it transitions through named phases and
> emits transition/completion events, but it never bumps a version, opens a PR,
> pushes a tag, or publishes a package. The caller tells the FSM whether each phase
> "succeeded"; the node does not execute the phase.
>
> Everything in the **"Target design (NOT YET IMPLEMENTED)"** section below — the
> 14-phase pipeline, the per-repo `gh pr create` / `git tag` / PyPI-publish steps,
> the idempotency dedup table, and crash-safe state-file resume — describes the
> intended future behavior. **None of it runs today.** Do not invoke `/release`
> expecting it to cut a real release.
>
> Full handler implementation is tracked in **OMN-8004** (historical
> placeholder-origin ticket; do not reopen). Honesty reconciliation: **OMN-13148**.

## Usage

```
/release omniclaude omnibase_core        # (placeholder) parse args, run FSM only
/release --all --bump patch              # (placeholder) parse args, run FSM only
/release --dry-run                       # (placeholder) parse args, run FSM only
/release --resume <run_id>               # (placeholder) resume flag is parsed but no state file is persisted
/release --gate-attestation <token>      # (placeholder) token is parsed only
```

> All flags are parsed by the node CLI (`__main__.py`) and threaded into the start
> command, but no flag currently produces a release side effect.

## What actually executes today

### Step 1 — Parse arguments

The node CLI (`omnimarket.nodes.node_release.__main__`) parses `repos`, `--all`,
`--bump`, `--dry-run`, `--resume`, `--skip-pypi-wait`, `--autonomous`, and
`--gate-attestation`, builds a `ModelReleaseStartCommand`, and prints it as JSON.
This is for contract verification only — no repo is scanned, no commits are read.

### Step 2 — Initialize node (contract verification)

```bash
onex run-node node_release \
  --input '{"repos": [], "bump": null, "dry_run": false, "autonomous": false}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it
directly, do not produce prose. The handler is a structural placeholder; full
migration is tracked in OMN-8004.

### Step 3 — Run the placeholder FSM

`HandlerRelease` (`omnimarket/.../node_release/handlers/handler_release.py`) is a
**pure-logic FSM with no external I/O** (its own docstring: "Pure logic — no
external I/O"). It exposes `start()`, `advance()`, `run_full_pipeline()`, and
`handle()`. `run_full_pipeline()` walks the phase sequence below, emitting a
`ModelReleasePhaseEvent` per transition and a `ModelReleaseCompletedEvent` at the
end. Whether a phase "succeeds" is supplied by the caller via `phase_success` /
`phase_results` — the handler does **not** bump versions, create PRs, tag, or
publish.

**Actual phase enum (`EnumReleasePhase`, 9 states):**

```
IDLE → BUMP_VERSIONS → PIN_CROSS_REPO → CREATE_PRS → MERGE → TAG → PUBLISH → DONE
                                                                              (FAILED)
```

These are **labels only** — advancing to `TAG` does not push a git tag; advancing
to `PUBLISH` does not publish to PyPI. The handler also implements a circuit
breaker: `max_consecutive_failures` (default 3) consecutive failures transition the
FSM to `FAILED`. Per-phase repo metrics (`repos_succeeded` / `repos_failed` /
`repos_skipped`) are accumulated from caller-supplied counts, not computed from
real release outcomes.

### Step 4 — Report

The completion event carries `final_phase` and the accumulated repo counts. There
is no release table, no PR/tag/PyPI status, and no `ModelSkillResult` file written
by the node today.

## Models that exist today

| Model | Purpose |
|-------|---------|
| `EnumReleasePhase` | 9-state FSM enum (see above) |
| `ModelReleaseCommand` / `ModelReleaseStartCommand` | Start command DTO |
| `ModelReleaseState` | Frozen FSM state (current phase, repos, counts, circuit-breaker) |
| `ModelReleasePhaseEvent` | Emitted per phase transition |
| `ModelReleaseCompletedEvent` | Emitted on terminal phase |

Contract: `omnimarket/src/omnimarket/nodes/node_release/contract.yaml`
(subscribe `onex.cmd.omnimarket.release-start.v1`, publish
`onex.evt.omnimarket.release-completed.v1`).

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_release/ (STRUCTURAL PLACEHOLDER — pure FSM, no I/O)
contract   -> node_release/contract.yaml
migration  -> OMN-8004 (full handler implementation, historical origin — do not reopen)
honesty    -> OMN-13148 (doc-vs-impl reconciliation)
```

---

# Target design (NOT YET IMPLEMENTED)

> **Everything below this line describes intended future behavior and does NOT run
> today.** The routed `node_release` handler performs none of these git / `gh` /
> `uv` / PyPI operations. This section is preserved as the design target for the
> OMN-8004 migration. Treat every "create PR", "push tag", "publish", "write state
> file", and "dedup" statement below as a specification, not a description of
> current behavior.

## Target execution — release phases

The target pipeline processes repos in dependency-tier order (tier 0 → tier N):

1. **GATE**: Validate gate attestation (if provided) or proceed automatically
2. **BUMP**: For each repo — infer or apply version bump; update `pyproject.toml` + `__version__` <!-- skill-boundary-ok: repo iteration is performed by node_release, this skill only dispatches -->
3. **PIN**: Update cross-repo dependency pins in downstream repos
4. **PR**: Create release PR per repo via `gh pr create`; enable auto-merge
5. **MERGE**: Wait for CI + merge queue; confirm merged
6. **TAG**: `git tag v{version}` + push; trigger PyPI publish workflow
7. **WAIT**: Poll PyPI for package availability (unless `--skip-pypi-wait`)
8. **VERIFY**: Confirm installed version matches released version

Target reporting: display a release table (repo, old version, new version, PR, tag,
PyPI status) and write `ModelSkillResult` to
`$ONEX_STATE_DIR/skill-results/{context_id}/release.json`.

## Target safety

- Proceeds automatically — no Slack approval gate
- `--dry-run` produces zero side effects: no bumps, PRs, tags, or PyPI triggers
- Resume support: state written after each phase; `--resume <run_id>` skips completed phases
- Cross-repo dependency pins use exact ==X.Y.Z format for determinism (exact pin policy)

## Target dependency graph

Repos are released in dependency-tier order to guarantee downstream consumers get updated pins:

| Tier | Repos |
|------|-------|
| Tier 1 | omnibase_compat |
| Tier 2 | omnibase_core |
| Tier 3 | omnibase_spi |
| Tier 4 | omnibase_infra |
| Tier 5 | omniclaude, omniintelligence, omnimemory, omnimarket |
| Tier 6 | omninode_infra, omnidash |

Tier N+1 repos pin the released version of Tier N repos. If a Tier 2 release fails,
Tiers 3 through 6 are BLOCKED.

## Target error table

| Error Code | Condition | Behavior |
|------------|-----------|----------|
| GRAPH_DRIFT | Dependency graph differs from last snapshot | Abort and report |
| NOTHING_TO_RELEASE | No version bump inferred from commits | Skip repo (not an error) |
| LINT_FAILED | ruff/mypy CI gate fails | TIER_BLOCKED for downstream |
| PYPI_TIMEOUT | Package not available on PyPI after timeout | Mark as PARTIAL |
| TIER_BLOCKED | Upstream tier failed | Skip repo, continue with others |
| GATE_REJECTED | Gate attestation invalid | Abort entire release |

## Target ModelSkillResult

```python
class ModelSkillResult:
    status: Literal["SUCCESS", "PARTIAL", "FAILED", "DRY_RUN"]
    repos_succeeded: list[str]
    repos_failed: list[str]
    run_id: str
```

## Target phase state machine

> **NOT IMPLEMENTED.** This 14-phase per-repo state machine is the migration
> target; it does not match the 9-state FSM that runs today (see "Actual phase
> enum" above). The target FSM intends each repo to progress through:

```
PLANNED → WORKTREE → BUMPED → PINNED → CHANGELOG → LOCKED
       → LINT → COMMITTED → PUSHED → PR_CREATED → MERGED
       → TAGGED → PUBLISHED → DONE
```

Target phases: PLANNED, WORKTREE, BUMPED, PINNED, CHANGELOG, LOCKED, LINT,
COMMITTED, PUSHED, PR_CREATED, MERGED, TAGGED, PUBLISHED, DONE.

The target design writes state atomically after each transition using a temp file
+ rename to guarantee crash-safe resume. **No state file is written today.**

## Target idempotency

> **NOT IMPLEMENTED.** The target design intends to deduplicate all mutations on
> resume. The handler performs none of these checks today:

| Operation | Idempotency Key |
|-----------|----------------|
| PR dedupe | Check `gh pr list --head <branch>` before creating |
| Tag dedupe | Check `git tag -l <version>` before tagging |
| Worktree reuse | Reuse existing worktree at `$ONEX_WORKTREES_ROOT/<run_id>/<repo>` |

## Target cross references

- **merge-sweep**: Used to verify merges succeeded and queues are clear
- **pr-safety**: Validates PR is mergeable (no conflicts, no blocking reviews)
- **release.yml**: GitHub Action triggered post-merge for PyPI publish
- **auto-tag-reusable**: Reusable workflow for git tag + push
