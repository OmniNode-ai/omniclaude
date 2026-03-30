---
description: Full PR readiness loop — resolve merge conflicts, address all review comments and CI failures, then iterate local-review until N consecutive clean passes
mode: full
version: 1.1.0
level: intermediate
debug: false
category: workflow
tags:
  - pr
  - review
  - conflicts
  - code-quality
  - iteration
author: OmniClaude Team
args:
  - name: pr_number
    description: PR number or URL (auto-detects from current branch if omitted)
    required: false
  - name: --required-clean-runs
    description: "Consecutive clean local-review passes required before done (default 4)"
    required: false
  - name: --max-iterations
    description: "Maximum local-review cycles (default 10)"
    required: false
  - name: --skip-conflicts
    description: Skip merge conflict resolution phase
    required: false
  - name: --skip-pr-review
    description: Skip PR review comments and CI failures phase
    required: false
  - name: --skip-local-review
    description: Skip local-review clean-pass loop phase
    required: false
  - name: --no-ci
    description: Skip CI failure analysis (passed through to pr-review-dev)
    required: false
  - name: --no-push
    description: Make all fixes but do not push to remote
    required: false
  - name: --no-automerge
    description: Skip enabling GitHub automerge after all phases complete
    required: false
---

# PR Polish

## Headless Mode (Overnight Pipelines)

pr-polish is designed for headless invocation by merge-sweep during overnight pipeline runs.
It does not require interactive approval gates and is safe to run via `claude -p`.

**Minimum tool set for headless pr-polish:**

```bash
ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,Task,TaskCreate,TaskUpdate,TaskGet,TaskList,SendMessage"
claude -p --allowedTools "${ALLOWED_TOOLS}" \
  "Run the pr-polish skill for PR #<N> --required-clean-runs 2."
```

**Failure doctrine in headless mode:**
- **Ambiguity** (cannot determine which PR, conflicting state): write
  `$ONEX_STATE_DIR/pr-polish/ambiguity_<pr>_<ts>.json` and exit non-zero — never guess
- **Missing credentials** (gh not authed, no push access): emit structured error JSON to stderr,
  exit 2 — never silently degrade to read-only
- **Blocked tool** (tool not in allowlist): log the denied tool name and exit 4 — never
  substitute an unpermitted tool or silently skip the step
- **Max iterations hit** (cannot reach N clean passes): emit `status: partial` result to
  `$ONEX_STATE_DIR/pr-polish/result_<pr>.json` and exit 5 — do NOT re-run phases already
  completed (idempotency via phase result files)
- **Unresolvable conflict** (3-way merge cannot be auto-resolved): emit `status: blocked`,
  write diagnosis, exit 6 — do NOT leave a partially resolved conflict

**Checkpointable state:** Each phase writes its result before starting the next:
- `$ONEX_STATE_DIR/pr-polish/<pr>/phase1_conflicts.json` — conflict resolution result
- `$ONEX_STATE_DIR/pr-polish/<pr>/phase2_review.json` — PR review + CI result
- `$ONEX_STATE_DIR/pr-polish/<pr>/phase3_local_review.json` — local-review loop result

On re-run, phases with existing `status: completed` result files are skipped (idempotent).

## Dispatch Surface: Agent Teams (1 worker)

pr-polish uses a single Agent Teams background worker with Edit/Write/Bash tools. The team
lead (this session) creates a single-worker team, dispatches the polish task, and monitors
for completion.

### Lifecycle

```
1. TeamCreate(team_name="pr-polish-{pr_number}")
2. Agent(name="polisher-{pr_number}", team_name="pr-polish-{pr_number}",
         prompt="Execute pr-polish for PR #{pr_number}. <full context and args>")
3. Worker executes all three phases (conflicts, review, local-review) in background
4. Worker reports completion via SendMessage(to="team-lead") with phase results
5. TeamDelete(team_name="pr-polish-{pr_number}") after worker completes or times out
```

### Worker Tools

The dispatched worker requires: `Bash, Read, Write, Edit, Glob, Grep, Skill`

### Failure on Dispatch

If Agent Teams dispatch fails (TeamCreate error, Agent tool unavailable, auth error):
**STOP immediately.** Report the exact error to the user and wait for direction. Do NOT fall
back to direct Bash, Read, Edit, Write, or Glob calls -- falling back bypasses observability,
context management, and the orchestration layer.

## Overview

Three-phase PR readiness workflow that takes a branch from "open PR" to "clean and ready to merge":

0. **Branch Verification** (OMN-6253, OMN-6457) — fetch the actual PR branch name from the GitHub API and verify we are on the correct branch before any work begins. Never trust the dispatcher's branch name.

### Branch Name Verification (mandatory — OMN-6457)

**CRITICAL**: Before creating a worktree or pushing to a branch, ALWAYS fetch the current branch name:

```bash
BRANCH=$(gh pr view {pr_number} --json headRefName -q '.headRefName')
```

**NEVER**:
- Use a branch name from a previous step, variable, or cached value
- Assume the branch name from the ticket ID or PR title
- Use a branch name provided in the initial dispatch prompt without re-verifying

This prevents the 4-cycle waste observed in F5 where agents pushed to the wrong branch.
1. **Conflict Resolution** — detect and resolve merge conflicts against the base branch
2. **PR Review + CI Fix** — fetch all open review comments and CI failures, fix Critical/Major/Minor via `pr-review-dev`
3. **Local Review Loop** — run `local-review` until N consecutive passes with nothing but nits (default N=4)

**Announce at start:** "I'm using the pr-polish skill to bring PR #{pr_number} to merge-ready state."

> **Classification System**: Uses onex pr-review keyword-based classification throughout.
> ALL Critical/Major/Minor issues MUST be resolved. Only Nits are optional.
> See: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md` for full priority definitions.

## Quick Start

```
/pr-polish                              # Auto-detect PR from current branch, 4 clean passes
/pr-polish 226                          # Specific PR number
/pr-polish 226 --required-clean-runs 2  # Faster iteration (2 clean passes)
/pr-polish 226 --skip-conflicts         # Skip conflict phase (no conflicts expected)
/pr-polish 226 --skip-pr-review         # Only run local-review loop
/pr-polish 226 --skip-local-review      # Only resolve conflicts + pr-review-dev
/pr-polish 226 --no-ci                  # Skip CI failure fetch (PR review only)
/pr-polish 226 --no-push                # Fix everything locally, don't push
/pr-polish 226 --no-automerge           # Polish PR but don't arm automerge
```

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `pr_number` | auto | PR number or URL (auto-detect from branch if omitted) |
| `--required-clean-runs <n>` | 4 | Consecutive clean local-review passes required |
| `--max-iterations <n>` | 10 | Max local-review cycles |
| `--skip-conflicts` | false | Skip Phase 0 conflict resolution |
| `--skip-pr-review` | false | Skip Phase 1 PR review + CI fix |
| `--skip-local-review` | false | Skip Phase 2 local-review loop |
| `--no-ci` | false | Skip CI failures in Phase 1 (PR review only) |
| `--no-push` | false | Apply all fixes without pushing to remote |
| `--no-automerge` | false | Skip arming GitHub automerge after all phases complete |

## Dispatch Contracts (Execution-Critical)

**You are an orchestrator.** You manage phase sequencing and state. You do NOT fix issues, resolve conflicts, or review code yourself — all three phases are delegated.

**Rule: The coordinator must NEVER call Edit(), Write(), or analyze code directly.**

### Phase 0: Conflict Resolution — dispatch to team worker

Only runs if `git status` shows unmerged paths. The worker handles this as part of its
three-phase execution:

```
SendMessage(to="polisher-{pr_number}",
  body="Resolve all merge conflicts on this branch. Base branch: {base_branch}.

    Steps:
    1. Run: git status (identify conflicted files)
    2. For each conflicted file: read the file, understand both sides, apply the correct resolution
    3. git add <resolved files>
    4. git commit -m 'fix(merge): resolve conflicts against {base_branch}'
    5. If --no-push is NOT set: git push

    Resolution rules:
    - Prefer the more recent/complete implementation
    - When in doubt, keep BOTH sides merged correctly (don't blindly discard either)
    - Never leave conflict markers in the file
    - Run linting after resolution to catch any issues introduced

    Report: list of resolved files and brief description of resolution strategy for each."
)
```

### Review Comment Handling (mandatory before thread resolution — OMN-6456)

Before resolving any review threads, the agent MUST follow this 4-step sequence:

1. **Fetch all review threads**: `gh pr view {number} --json reviews,reviewThreads`
2. **Identify unresolved threads**: filter `reviewThreads` where `isResolved == false`
3. **For each unresolved thread**:
   a. Read the comment body and understand the requested change
   b. If the comment is valid and actionable: implement the fix, commit, then reply acknowledging the fix
   c. If the comment is not applicable (e.g., CodeRabbit suggestion that doesn't apply): reply with a specific reason why, then resolve
   d. **NEVER** resolve a thread without either fixing the issue or replying with a reason
4. **After all threads addressed**: push fixes, then resolve threads that were fixed

**Hard rule**: `gh api ... -X PUT` to resolve a thread is FORBIDDEN unless the thread has a reply from this agent explaining what was done.

### Phase 1: PR Review + CI Fix — invoke pr-review-dev skill

```
Skill(skill="onex:pr_review_dev", args="{pr_number} {--no-ci if set}")
```

This handles fetching PR review comments, CI failures, running multi-agent parallel-build for all Critical/Major/Minor issues, and offering to fix nitpicks.

### Phase 2: Local Review Loop — invoke local-review skill

```
Skill(skill="onex:local_review", args="--required-clean-runs {required_clean_runs} --max-iterations {max_iterations}")
```

Runs until `required_clean_runs` consecutive clean passes (only nits). After clean passes, if `--no-push` is NOT set: `git push`.

### Phase 3: Resolve Review Threads — runs inline before automerge

Runs only if `--no-automerge` is NOT set and `--no-push` is NOT set.

Before arming automerge, resolve any unresolved review threads that would block merge
(repos with `required_conversation_resolution: true`). Uses `resolve_review_threads()`
from `@_lib/pr-safety/helpers.md`.

For each unresolved thread:
1. Read the comment body, file path, and line reference
2. Check current code at the referenced location
3. Classify disposition: `addressed` | `not_applicable` | `intentional` | `deferred`
4. Post a reply explaining WHY the thread is being resolved (1-2 sentences)
5. Resolve the thread

**Critical**: Never resolve a thread without posting a reply. Silent resolution
defeats the purpose of code review.

Reports: `Resolved N review threads (M addressed, K not_applicable, J intentional, L deferred).`

If no unresolved threads exist, skip silently.

### Finalize: Enable Automerge — runs inline after thread resolution

Runs only if `--no-automerge` is NOT set and `--no-push` is NOT set.

```bash
gh auth status || { echo "ERROR: not logged into GitHub CLI"; exit 1; }
# Use {pr_number} and {repo} from resolved skill args — no cwd-dependence
gh pr merge --auto --squash "{pr_number}" --repo "{repo}"
# GitHub merges when all branch protection requirements are satisfied.
```

Idempotent — safe to run even if automerge was already armed.
Reports: `Automerge armed on PR #{pr_number}.`

---

## Phase Sequencing

```
Phase 0: Conflict Resolution
    ↓ (skip if --skip-conflicts or no conflicts found)
Phase 1: PR Review + CI Fix (pr-review-dev)
    ↓ (skip if --skip-pr-review)
Phase 2: Local Review Loop (local-review --required-clean-runs N)
    ↓ (skip if --skip-local-review)
Push (if not --no-push)
    ↓
Phase 3: Resolve Review Threads (if not --no-automerge and not --no-push)
    ↓
Enable automerge (if not --no-automerge and not --no-push)
    ↓
Final Report
```

Each phase is independent. A phase failure is reported but does not block subsequent phases unless it leaves the working tree in a conflicted state.

## Status Indicators

- `Phase 0: No conflicts — skipped` — clean merge state
- `Phase 0: Resolved N files` — conflicts resolved and committed
- `Phase 1: N issues fixed (M CI failures + K review comments)` — pr-review-dev complete
- `Phase 1: No issues found` — already clean
- `Phase 2: Clean — Confirmed (N/N clean runs)` — local-review passed
- `Phase 2: Max iterations reached` — hit limit with blocking issues remaining
- `DONE: PR #{pr_number} is merge-ready — automerge armed` — all phases green, automerge enabled
- `DONE: PR #{pr_number} is merge-ready — automerge NOT enabled (--no-automerge)` — phases green, automerge skipped

## Detailed Orchestration

Full orchestration logic (argument parsing, conflict detection heuristics, phase state tracking,
error handling per phase, push behavior, final report format) is documented in `prompt.md`.
The dispatch contracts above are sufficient to execute all three phases.

## CI Failure Taxonomy

When Phase 1 encounters CI failures (via `pr-review-dev`), they are classified into the
following categories. Each category has a defined fix strategy and retry budget.

### Categories

| Category | Examples | Fix Strategy | Max Retries |
|----------|----------|--------------|-------------|
| **Lint/Format** | ruff, mypy, black, isort | Auto-fix: `ruff check --fix`, `ruff format` | 1 (deterministic) |
| **Type Check** | mypy strict, pyright | Targeted type annotation fixes | 2 |
| **Unit Test** | pytest failures, assertion errors | Read failure, fix logic or test | 2 |
| **Integration Test** | Service connectivity, fixture failures | Check env, retry with backoff | 1 |
| **Build/Package** | Import errors, missing deps, build failures | Fix imports, update pyproject.toml | 2 |
| **Security Scan** | Secret detection, dependency audit | Remove secrets, update deps | 1 |
| **Timeout** | CI job exceeded time limit | Optimize or split test, increase limit | 1 |
| **Flaky** | Passes on retry without code change | Re-trigger CI run (no code fix) | 2 |

### Fix Strategies

**Lint/Format** (deterministic, highest confidence):
```
1. Run: ruff check --fix . && ruff format .
2. Run: mypy src/ --strict (verify no regressions)
3. Stage, commit, push
```

**Unit Test** (requires understanding):
```
1. Fetch failure log via: ${CLAUDE_PLUGIN_ROOT}/_bin/ci-status.sh --pr {N} --repo {repo}
2. Read failing test and source under test
3. Determine: bug in code or bug in test
4. Fix and push
```

**Flaky** (no code change):
```
1. Detect: same test passed in previous run on same SHA
2. Re-trigger: gh run rerun {run_id} --repo {repo} --failed
3. If fails again on retry: escalate to Unit Test category
```

### Retry Budget

The total retry budget across all CI fix cycles is controlled by `max_ci_fix_cycles`
(default: 3 from ticket-pipeline policy). Each category consumes from this shared budget.

**Budget allocation strategy**:
- Cycle 1: Fix all Lint/Format + Type Check issues (high confidence)
- Cycle 2: Fix Unit Test + Build failures (medium confidence)
- Cycle 3: Final attempt on remaining failures or re-trigger flaky tests

If the budget is exhausted with failures remaining, the skill reports `status: capped`
and the pipeline escalates to a Slack MEDIUM_RISK gate.

### CI Status Extraction

In STANDALONE mode, CI failure details are extracted via `_bin/ci-status.sh`:

```bash
# Snapshot current CI status
${CLAUDE_PLUGIN_ROOT}/_bin/ci-status.sh --pr {N} --repo {repo}

# Wait for terminal state (poll mode)
${CLAUDE_PLUGIN_ROOT}/_bin/ci-status.sh --pr {N} --repo {repo} --wait --timeout 3600
```

The script returns structured JSON with check names, states, conclusions, and a
`log_excerpt` field containing the last 200 lines of the failed run log.

## See Also

- `local-review` skill (Phase 2 -- iterative local review loop)
- `pr-review-dev` skill (Phase 1 -- PR review comments + CI failures)
- `pr-review` skill (keyword-based priority classification reference)
- `ticket-pipeline` skill (chains pr-polish as its review + merge phase)
- `_bin/ci-status.sh` -- STANDALONE CI status extraction backend
