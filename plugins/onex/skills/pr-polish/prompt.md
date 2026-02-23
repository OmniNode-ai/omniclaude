# PR Polish — Orchestration Details

> Full execution logic for the `pr-polish` skill.
> Load this file when you need implementation details beyond the SKILL.md dispatch contracts.

---

## Argument Parsing

Parse from `$ARGUMENTS` string:

```python
# Defaults
pr_number        = None          # auto-detect from branch if omitted
required_clean   = 4             # --required-clean-runs
max_iterations   = 10            # --max-iterations
skip_conflicts   = False         # --skip-conflicts
skip_pr_review   = False         # --skip-pr-review
skip_local_review = False        # --skip-local-review
no_ci            = False         # --no-ci
no_push          = False         # --no-push

# Parse
for token in $ARGUMENTS.split():
    if token is a plain integer or github PR URL -> pr_number = extract_number(token)
    if token == "--required-clean-runs" -> required_clean = next_token as int
    if token == "--max-iterations"      -> max_iterations = next_token as int
    if token == "--skip-conflicts"      -> skip_conflicts = True
    if token == "--skip-pr-review"      -> skip_pr_review = True
    if token == "--skip-local-review"   -> skip_local_review = True
    if token == "--no-ci"               -> no_ci = True
    if token == "--no-push"             -> no_push = True

# Auto-detect PR number from current branch if not provided
if pr_number is None:
    branch = run("git rev-parse --abbrev-ref HEAD")
    pr_number = run(f"gh pr view {branch} --json number --jq .number")
    # If that fails (no PR for branch), pr_number stays None
    # Phase 1 (pr-review-dev) will also fail gracefully in that case
```

---

## Phase 0: Conflict Resolution

### 0.1 — Detect conflicts

```python
if skip_conflicts:
    print("Phase 0: Skipped (--skip-conflicts)")
    goto Phase 1

status = run("git status --porcelain")
conflicted_files = [
    line.strip().split()[-1]
    for line in status.splitlines()
    if line[:2] in ("UU", "AA", "DD", "AU", "UA", "DU", "UD", "UC", "CU")
]

if not conflicted_files:
    print("Phase 0: No conflicts — skipped")
    goto Phase 1

print(f"Phase 0: {len(conflicted_files)} conflicted file(s) detected — resolving...")
print("  " + "\n  ".join(conflicted_files))
```

### 0.2 — Detect base branch

```python
base_branch = run("git rev-parse --abbrev-ref @{upstream}").strip()
# Fallback: look at PR base
if base_branch is empty or error:
    if pr_number:
        base_branch = run(f"gh pr view {pr_number} --json baseRefName --jq .baseRefName").strip()
    if base_branch is still empty:
        base_branch = "main"
```

### 0.3 — Dispatch conflict resolver

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Resolve merge conflicts",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

    Resolve all merge conflicts on this branch. Base branch: {base_branch}.

    Conflicted files:
    {conflicted_files joined with newlines}

    Resolution steps:
    1. For each conflicted file:
       a. Read the file in full — understand both the HEAD and incoming changes
       b. Determine the correct merge: keep both? keep HEAD? keep incoming?
       c. Edit the file to apply the resolution — remove ALL conflict markers
       d. Run: git add {file}
    2. Verify no conflict markers remain: grep -r '<<<<<<<' . --include='*.py' --include='*.md' --include='*.yaml' --include='*.json'
    3. Run linting on changed files: ruff check {changed_files} (if Python files changed)
    4. Commit: git commit -m 'fix(merge): resolve conflicts against {base_branch} [pr-polish]'
    5. Confirm: git status (should show clean working tree)

    Resolution rules:
    - Prefer the more complete/correct implementation when logic differs
    - When both sides add new content, include BOTH (merge rather than discard)
    - Never silently drop functionality from either side
    - If uncertain about intent: include both with a comment noting the merge

    Return JSON: {\"resolved\": [\"file1\", \"file2\"], \"strategy\": {\"file1\": \"kept both\", \"file2\": \"kept HEAD\"}}"
)
```

### 0.4 — Handle conflict resolution result

```python
if resolution_agent returned error or conflicts remain:
    print("Phase 0: ERROR — conflict resolution failed. Manual intervention required.")
    print("  Run: git status  to see remaining conflicts")
    # Do NOT proceed if conflicts remain — git will block commits
    exit with phase_0_status = "FAILED"
else:
    commits_made.append(resolution_commit_sha)
    print(f"Phase 0: Resolved {len(resolved_files)} file(s) — committed")
    phase_0_status = "OK"
```

---

## Phase 1: PR Review + CI Fix

### 1.1 — Check preconditions

```python
if skip_pr_review:
    print("Phase 1: Skipped (--skip-pr-review)")
    goto Phase 2

if phase_0_status == "FAILED":
    print("Phase 1: Skipped (Phase 0 left conflicts unresolved)")
    goto Phase 2

if pr_number is None:
    print("Phase 1: Skipped (no PR number — not on a PR branch)")
    goto Phase 2
```

### 1.2 — Invoke pr-review-dev

```python
print(f"Phase 1: Running pr-review-dev on PR #{pr_number}...")

no_ci_flag = "--no-ci" if no_ci else ""
Skill(skill="onex:pr-review-dev", args=f"{pr_number} {no_ci_flag}")

# pr-review-dev handles:
# - fetching PR review comments via collate-issues-with-ci
# - fetching CI failures (unless --no-ci)
# - dispatching parallel-solve for Critical/Major/Minor
# - offering to fix nitpicks
# - does its own push internally unless --no-push is passed
#   (NOTE: pr-review-dev does not accept --no-push; if no_push is set,
#    the orchestrator will skip the push step at the end)
```

### 1.3 — Phase 1 complete

```python
print("Phase 1: PR review + CI fix complete")
phase_1_status = "OK"
```

---

## Phase 2: Local Review Loop

### 2.1 — Check preconditions

```python
if skip_local_review:
    print("Phase 2: Skipped (--skip-local-review)")
    goto Finalize

if phase_0_status == "FAILED":
    print("Phase 2: Skipped (Phase 0 left conflicts unresolved)")
    goto Finalize
```

### 2.2 — Invoke local-review

```python
print(f"Phase 2: Running local-review (--required-clean-runs {required_clean}, --max-iterations {max_iterations})...")

Skill(
  skill="onex:local-review",
  args=f"--required-clean-runs {required_clean} --max-iterations {max_iterations}"
)

# local-review handles:
# - gathering all changes since base branch
# - iterating: review -> fix -> commit -> repeat
# - stopping when required_clean consecutive clean runs are achieved
# - reporting final status
```

### 2.3 — Evaluate result

```python
if local-review status is "Clean - Confirmed" or "Clean with nits - Confirmed":
    phase_2_status = "OK"
    print(f"Phase 2: {required_clean}/{required_clean} clean passes — confirmed")
elif local-review status is "Max iterations reached":
    phase_2_status = "PARTIAL"
    print(f"Phase 2: Max iterations reached — some issues may remain")
else:
    phase_2_status = "ERROR"
    print(f"Phase 2: Review loop encountered an error — {local_review_status}")
```

---

## Finalize

### Push

```python
if not no_push and (phase_0_status == "OK" or phase_1_status == "OK" or phase_2_status == "OK"):
    result = run("git push")
    if result.returncode != 0:
        print("Warning: push failed — changes are committed locally")
        print("  Run: git push  to push manually")
    else:
        print("Pushed to remote.")
```

### Final Report

```
======================================
PR Polish — Final Report
======================================
PR:    #{pr_number} ({branch})
Base:  {base_branch}

Phase 0 — Conflict Resolution:   {phase_0_status}
  {resolved_files_summary or "No conflicts"}

Phase 1 — PR Review + CI Fix:    {phase_1_status}
  {issues_fixed_summary or "No issues or skipped"}

Phase 2 — Local Review Loop:     {phase_2_status}
  {clean_passes_summary or "Skipped"}

Push:  {pushed | skipped (--no-push) | failed}

======================================
{final_verdict}
======================================
```

`final_verdict` values:
- `DONE: PR #N is merge-ready` — all phases OK, all clean passes achieved
- `DONE: PR #N is merge-ready (with nits)` — all phases OK, only nits remain
- `PARTIAL: PR #N has remaining issues — see Phase 2 status` — max iterations hit
- `BLOCKED: Phase 0 conflict resolution failed — manual fix required` — unresolved conflicts

---

## Error Handling

| Failure | Behavior | Next Phase |
|---------|----------|------------|
| No PR found for branch | Phase 1 skipped | Phase 2 runs normally |
| Conflict resolution failed | Phase 1 + 2 skipped | Report BLOCKED |
| Conflict markers remain after resolution | Abort phases 1+2, report BLOCKED | Skip |
| pr-review-dev fails or no issues | Report and continue | Phase 2 runs |
| local-review max iterations hit | Report PARTIAL | Finalize |
| local-review agent/parse error | Report error | Finalize |
| Push fails | Warn, commits are local | Finalize |

---

## Implementation Notes

### Conflict Detection Heuristics

The two-char git status codes for unmerged paths:

| Code | Meaning |
|------|---------|
| `UU` | Both modified |
| `AA` | Both added |
| `DD` | Both deleted |
| `AU` | Added by us |
| `UA` | Added by them |
| `DU` | Deleted by us |
| `UD` | Deleted by them |

### When to Re-run Phases

If a phase commits new changes, subsequent phases pick them up automatically because:
- Phase 1 (`pr-review-dev`) fetches the current state of the PR
- Phase 2 (`local-review`) diffs against the base branch — picks up all committed changes

### PR Number Auto-Detection

The auto-detect flow (in order of preference):

```
1. gh pr view HEAD --json number --jq .number
2. gh pr list --head $(git branch --show-current) --json number --jq '.[0].number'
3. None (phases that need PR number are skipped)
```

---

## Example Session

```
Announce: "I'm using the pr-polish skill to bring PR #226 to merge-ready state."

Phase 0: Conflict Resolution
  git status → 2 conflicted files: [src/foo.py, tests/test_foo.py]
  Base branch: main
  [dispatch polymorphic-agent to resolve conflicts]
  Phase 0: Resolved 2 file(s) — committed (fix(merge): resolve conflicts against main)

Phase 1: PR Review + CI Fix
  [invoke pr-review-dev skill with PR #226]
  pr-review-dev: Fetching PR review comments...
  pr-review-dev: Fetching CI failures...
  pr-review-dev: 3 MAJOR, 1 MINOR issues found
  pr-review-dev: [dispatches parallel-solve]
  pr-review-dev: Fixed 4 issues, 2 commits
  Phase 1: PR review + CI fix complete

Phase 2: Local Review Loop
  [invoke local-review --required-clean-runs 4 --max-iterations 10]
  local-review: Pass 1 — 1 Minor issue found, fixing...
  local-review: Pass 2 — Clean (1/4)
  local-review: Pass 3 — Clean (2/4)
  local-review: Pass 4 — Clean (3/4)
  local-review: Pass 5 — Clean (4/4)
  Phase 2: 4/4 clean passes — confirmed

Pushed to remote.

======================================
PR Polish — Final Report
======================================
PR:    #226 (epic/OMN-2511/OMN-2512/f084b6c3)
Base:  main

Phase 0 — Conflict Resolution:   OK
  Resolved 2 files (src/foo.py, tests/test_foo.py)

Phase 1 — PR Review + CI Fix:    OK
  Fixed 4 issues (3 Major + 1 Minor)

Phase 2 — Local Review Loop:     OK
  Clean — Confirmed (4/4 clean runs)

Push:  pushed

======================================
DONE: PR #226 is merge-ready
======================================
```
