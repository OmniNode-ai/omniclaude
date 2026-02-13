# Review Cycle Orchestration

You are executing the review-cycle skill. This prompt provides extended rationale,
argument parsing details, JSON handling, state tracking, error recovery, and a full
example session. The dispatch contracts in `SKILL.md` are authoritative for execution;
this file supplements them with implementation depth.

---

## Design Rationale

### Why review-cycle exists alongside local-review

`local-review` is a fully autonomous loop: it reviews, fixes, commits, and repeats
until clean or max iterations. The human sees output but makes no decisions during
execution. This is ideal for CI pipelines, automated ticket work, and overnight runs.

`review-cycle` is the interactive counterpart. It pauses at every phase boundary
for human approval. The user decides:

- Which scope to review
- Which severities to fix
- Whether to accept or reject each fix batch
- Whether to drill down into individual issues for learning
- When to commit and with what message
- Whether to iterate or stop

This makes review-cycle suitable for:

- Learning a new codebase (drill-down explanations teach the "why")
- Careful reviews where the human wants veto power per file
- Pair-programming-style sessions where the AI proposes and the human disposes
- Situations where the human suspects the AI may over-fix or misclassify

### Information hiding design

The review agent returns an opaque work order: issue IDs, file paths, line ranges,
one-line titles, and severity classifications. It does NOT return code snippets,
patches, or fix suggestions.

This is intentional:

1. **Separation of concerns**: The orchestrator routes work; it never interprets code.
   If the orchestrator could see code snippets, it would be tempted to make judgments
   about them, violating the dispatch-only constraint.

2. **Token efficiency**: Code snippets in the review output would be duplicated when
   passed to the fix agent. The fix agent reads the files directly.

3. **Correctness**: Code in a JSON payload gets mangled by escaping. Having the fix
   agent read the actual file avoids escape-related bugs.

4. **Drill-down on demand**: When the user wants to understand an issue, the explain
   agent reads the file fresh and produces a rich explanation. This is better than
   a stale snippet from the review phase.

### The hybrid approval model

The default flow is batch approval: all fixes in a severity tier are applied at once,
and the user accepts or rejects the entire batch. This is fast.

Drill-down is available on demand: if the user selects "Review individually", each
modified file gets its own explanation + diff + accept/reject. This is thorough but
slower.

The hybrid approach lets the user choose speed vs. thoroughness per batch. Critical
issues might warrant individual review; minor issues might be batch-approved.

---

## Argument Parsing Details

### Parsing from `$ARGUMENTS`

```python
args = "$ARGUMENTS".split()

uncommitted = "--uncommitted" in args
no_learning = "--no-learning" in args
auto_mode = "--auto" in args

# Extract --since value
since_ref = None
if "--since" in args:
    idx = args.index("--since")
    if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
        since_ref = args[idx + 1]
        # Validate: git rev-parse --verify {since_ref}
    else:
        print("Error: --since requires a ref argument")
        exit(1)

# Extract --files value
files_glob = None
if "--files" in args:
    idx = args.index("--files")
    if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
        files_glob = args[idx + 1]
    else:
        print("Warning: --files requires a glob pattern. Reviewing all files.")
```

### Default values and flag interactions

| Flag | Default | Notes |
|------|---------|-------|
| `--uncommitted` | false | Mutually informative with `--since` (if both given, `--uncommitted` wins) |
| `--since` | auto-detect merge-base | Ignored when `--uncommitted` is set |
| `--files` | all changed files | Applied as a filter after diff |
| `--no-learning` | false | Only affects "Review individually" drill-down in Step 5 |
| `--auto` | false | Implies single pass, no AskUserQuestion, Critical+Major only |

### `--auto` + `--no-learning` interaction

In `--auto` mode, drill-down never happens (the user never selects "Review individually").
Therefore `--no-learning` has no effect in `--auto` mode. This is not an error; the
flag is simply irrelevant. Do not warn about it.

### Base ref detection (when `--since` is not provided and `--uncommitted` is not set)

```bash
git merge-base HEAD origin/main 2>/dev/null || \
git merge-base HEAD origin/master 2>/dev/null || {
    if git rev-parse --verify HEAD~10 >/dev/null 2>&1; then
        echo "Warning: Could not find merge-base, using HEAD~10" >&2
        echo "HEAD~10"
    else
        echo "Warning: Could not find merge-base, using initial commit" >&2
        git rev-list --max-parents=0 HEAD 2>/dev/null || echo "HEAD"
    fi
}
```

---

## JSON Parsing with Fallback

Agent dispatch returns text. The orchestrator must extract structured data from it.

### Step 1: Direct parse

```python
import json

try:
    result = json.loads(agent_output)
    # Validate expected keys exist
    assert "issues" in result
    assert "summary_counts" in result
except (json.JSONDecodeError, AssertionError, KeyError):
    # Fall through to Step 2
    pass
```

### Step 2: Extract from markdown code block

```python
import re

match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', agent_output, re.DOTALL)
if match:
    try:
        result = json.loads(match.group(1))
        assert "issues" in result
        assert "summary_counts" in result
    except (json.JSONDecodeError, AssertionError, KeyError):
        # Fall through to Step 3
        pass
```

### Step 3: Retry dispatch

Re-dispatch the same agent with a strengthened prompt:

```
"IMPORTANT: Your previous response could not be parsed as JSON.
Return ONLY a raw JSON object. No markdown formatting, no code blocks,
no explanatory text. Start with { and end with }."
```

If the retry also fails to parse, exit the current iteration with an error message:

```
"Error: Review agent output could not be parsed as JSON after retry.
Raw output has been logged. Please review manually or try again."
```

### Applying the same pattern to fix phase

The fix phase returns a different JSON schema (`applied_issue_ids`, `modified_files`,
etc.). Apply the same 3-step parse logic. The retry prompt should reference the fix
schema, not the review schema.

---

## State Tracking

Track the following across iterations:

```python
state = {
    "iteration_number": 0,       # 1-indexed (incremented at start of each iteration)
    "total_issues_found": 0,     # Cumulative across all iterations
    "total_issues_fixed": 0,     # Cumulative across all iterations
    "commits_made": [],          # List of {"hash": "abc1234", "message": "fix(review-cycle): ..."}
    "remaining_issues": [],      # From the latest review (replaced each iteration)
    "skipped_issues": [],        # Issues the user chose to skip (cumulative)
    "restore_point_exists": False # Whether git stash push succeeded
}
```

### Updating state

**After Step 2 (review dispatch)**:
```python
state["iteration_number"] += 1
new_issues = len(result["issues"])
state["total_issues_found"] += new_issues
state["remaining_issues"] = result["issues"]  # Replace, not append
```

**After Step 5 (fix execution)**:
```python
for batch_result in fix_results:
    state["total_issues_fixed"] += len(batch_result["applied_issue_ids"])
    # Remove fixed issues from remaining
    fixed_ids = set(batch_result["applied_issue_ids"])
    state["remaining_issues"] = [
        iss for iss in state["remaining_issues"]
        if iss["id"] not in fixed_ids
    ]
```

**After Step 5e "Skip this file"**:
```python
# Issues associated with skipped files go to skipped_issues
state["skipped_issues"].extend(skipped)
```

**After Step 6 (commit)**:
```python
state["commits_made"].append({
    "hash": git_rev_parse_short_head,
    "message": commit_message
})
```

---

## Error Recovery

### Git stash conflicts

If `git stash push -m "review-cycle-restore-point"` fails:

```python
stash_result = subprocess.run(
    ["git", "stash", "push", "-m", "review-cycle-restore-point"],
    capture_output=True, text=True
)
if stash_result.returncode != 0:
    print("Warning: Could not create restore point. "
          "'Discard all changes' will not be available.")
    state["restore_point_exists"] = False
else:
    state["restore_point_exists"] = True
```

When the user selects "Discard all changes" in Step 6 but no restore point exists:

```
"Cannot discard all changes: no restore point was created.
Use git commands manually to revert if needed."
```

### Fix agent modifies wrong files

After the fix agent returns, compare `modified_files` from its JSON response
against actual changes on disk:

```bash
git diff --name-only
```

If the actual diff includes files NOT in the agent's `modified_files` list:

```
"Warning: Fix agent modified unexpected files: {extra_files}
These files were NOT listed in the fix response.
Please review these changes before staging."
```

Show the unexpected file diffs and let the user decide in Step 5e whether to
include or exclude them.

### Partial batch failure

The fix agent may report some issues in `applied_issue_ids` and others in
`skipped_issue_ids` with errors. Handle this gracefully:

1. Stage only files associated with applied issues
2. Report skipped issues with their error reasons
3. Add skipped issues to `state["remaining_issues"]` (they were not fixed)
4. The user can choose to address them in the next iteration

### Review agent returns empty issues with non-zero counts

If `summary_counts` shows non-zero values but the `issues` array is empty (or
vice versa), trust the `issues` array as the source of truth. Recompute counts
from the actual issues:

```python
actual_counts = {"critical": 0, "major": 0, "minor": 0, "nit": 0}
for issue in result["issues"]:
    sev = issue["severity"].lower()
    if sev in actual_counts:
        actual_counts[sev] += 1
result["summary_counts"] = actual_counts
```

---

## Example Session

```
> /review-cycle

I'm using the review-cycle skill for guided local code review.

## Scope Selection

How would you like to scope this review?

1. All changes since base branch (origin/main)
2. Uncommitted only
3. Since specific commit/branch
4. Specific files

> 1

Capturing restore point...
Restore point created (git stash).

Dispatching review agent...

## Review Results (Iteration 1)

| Severity | Count | Blocking |
|----------|-------|----------|
| CRITICAL | 1     | Yes      |
| MAJOR    | 2     | Yes      |
| MINOR    | 1     | Yes      |
| NIT      | 1     | No       |

### Issues

#### CRITICAL
- ISS-001 | src/api/auth.py:45-52 | SQL injection in user query parameter

#### MAJOR
- ISS-002 | src/api/auth.py:89-91 | Missing password length validation
- ISS-003 | src/utils/parser.py:23-30 | Uncaught ValueError in JSON parser

#### MINOR
- ISS-004 | src/config.py:12-12 | Magic number should be named constant

#### NIT
- ISS-005 | src/models.py:56-56 | Unused import os

Which issues should be fixed?

1. All blocking issues (Critical+Major+Minor)
2. Critical only
3. Critical + Major
4. Report only (no fixes)

> 3

Dispatching fix agent for 1 CRITICAL issue...

Fixed 1 CRITICAL issue in 1 file (+5/-2)

Apply all fixes in this batch?

1. Apply all fixes in this batch
2. Review individually
3. Discard batch

> 2

--- ISS-001 | src/api/auth.py:45-52 | SQL injection in user query parameter ---

### The Problem
The `user_id` parameter is interpolated directly into the SQL query string
using f-string formatting. This allows an attacker to inject arbitrary SQL.

### Why It Matters
An attacker can extract, modify, or delete any data in the database by
crafting a malicious `user_id` value. This is a CRITICAL security vulnerability.

### Before
```python
query = f"SELECT * FROM users WHERE id = '{user_id}'"
cursor.execute(query)
```

### After
```python
query = "SELECT * FROM users WHERE id = %s"
cursor.execute(query, (user_id,))
```

--- diff: src/api/auth.py ---
@@ -45,3 +45,3 @@
-    query = f"SELECT * FROM users WHERE id = '{user_id}'"
-    cursor.execute(query)
+    query = "SELECT * FROM users WHERE id = %s"
+    cursor.execute(query, (user_id,))

Stage this file?
1. Stage this file
2. Skip this file

> 1

Staged: src/api/auth.py

Dispatching fix agent for 2 MAJOR issues...

Fixed 2 MAJOR issues in 2 files (+8/-3)

Apply all fixes in this batch?

1. Apply all fixes in this batch
2. Review individually
3. Discard batch

> 1

Staged: src/api/auth.py, src/utils/parser.py

## Commit Checkpoint

3 issues fixed across 2 files. What next?

1. Commit (message: "fix(review-cycle): fix 1 critical and 2 major issues")
2. Commit with custom message
3. Stage only (don't commit)
4. Discard current batch
5. Discard all changes

> 1

Created commit: abc1234 - fix(review-cycle): fix 1 critical and 2 major issues

## Continue?

1. Run another review iteration
2. Done
3. Show summary

> 2

## Review Cycle Complete

**Iterations**: 1
**Total issues found**: 5
**Total issues fixed**: 3
**Remaining issues**: 2

### Commits
1. abc1234 - fix(review-cycle): fix 1 critical and 2 major issues

### Remaining Issues
- ISS-004 | MINOR | src/config.py:12 | Magic number should be named constant
- ISS-005 | NIT | src/models.py:56 | Unused import os (optional)

**Status**: Fixes committed

Restore point cleaned up.

Next steps: Run tests, then push when ready. Consider fixing the remaining
MINOR issue in a follow-up iteration.
```

---

## `--auto` Mode Details

### Behavior

In `--auto` mode, the skill runs a single pass with no human interaction:

1. **Scope**: All changes since base branch (or `--since`/`--uncommitted` if provided)
2. **Review**: Dispatch review agent
3. **Fix Critical**: Dispatch fix agent for CRITICAL issues (if any)
4. **Fix Major**: Dispatch fix agent for MAJOR issues (if any)
5. **Commit**: Auto-commit with message format below
6. **Summary**: Display final summary and exit

Minor issues are NOT fixed in `--auto` mode. Only Critical and Major.

### Commit message format

```
fix(review-cycle): auto-fix {n} critical and {m} major issue(s)
```

If only one severity has issues:

```
fix(review-cycle): auto-fix {n} critical issue(s)
fix(review-cycle): auto-fix {m} major issue(s)
```

If no issues found:

No commit is created. Summary shows "Clean" status.

### Exit status indicators for `--auto`

- `Auto-fix complete` -- Issues found and fixed
- `Auto-fix complete with remaining` -- Fixed Critical+Major but Minor/Nit remain
- `Clean` -- No blocking issues found
- `Clean with nits` -- Only nits found, nothing to fix
- `Parse failed` -- Agent output could not be parsed
- `Agent failed` -- Agent crashed or timed out

### No AskUserQuestion in `--auto`

Every AskUserQuestion call in the flow is guarded:

```python
if not auto_mode:
    answer = AskUserQuestion(...)
else:
    answer = auto_default  # Pre-determined choice
```

Auto defaults:

| Step | Auto default |
|------|-------------|
| Step 1 (scope) | All changes since base branch |
| Step 4 (fix selection) | Critical + Major |
| Step 5e (batch approval) | Apply all fixes |
| Step 6 (commit) | Commit with auto message |
| Step 7 (continue) | Done (single pass) |

---

## Issue ID Lifecycle

Issue IDs (ISS-001, ISS-002, etc.) are scoped to a single review iteration. If
the user runs another iteration (Step 7 -> "Run another review iteration"), the
review agent generates a fresh set of IDs starting from ISS-001.

Do NOT carry over issue IDs between iterations. The `remaining_issues` list in
state tracking uses the full issue object (including the ID from its originating
iteration) for display purposes, but the fix agent in a new iteration will receive
freshly-assigned IDs from that iteration's review.

---

## Restore Point Lifecycle

```
Step 1.5: git stash push -m "review-cycle-restore-point"
    |
    v
Steps 2-7: Review/fix/commit cycles
    |
    |-- User selects "Discard all" (Step 6) --> git stash pop (restores original state)
    |
    |-- User completes normally (Step 8) --> git stash drop (clean up, changes committed)
    |
    |-- Error/exit --> stash remains (user can manually git stash pop)
```

The restore point covers the state at the START of the review cycle. Once the user
commits fixes, those commits exist in git history. "Discard all" pops the stash,
but committed changes would need `git reset` to undo (which is NOT automated by
the skill -- inform the user).
