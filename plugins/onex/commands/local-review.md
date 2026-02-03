---
name: local-review
description: Local code review loop that iterates through review, fix, commit cycles without pushing
tags: [review, code-quality, local, iteration]
---

# /local-review - Local Code Review Loop

Review local changes, fix issues, commit fixes, and iterate until clean or max iterations reached.

**Workflow**: Gather changes → Review → Fix → Commit → Repeat until clean

---

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--uncommitted` | false | Only review uncommitted changes (ignore committed) |
| `--since <ref>` | auto-detect | Base ref for diff (branch/commit) |
| `--max-iterations <n>` | 10 | Maximum review-fix cycles |
| `--files <glob>` | all | Glob pattern to limit scope |
| `--no-fix` | false | Report only, don't attempt fixes |
| `--no-commit` | false | Fix but don't commit (stage only) |

**Examples**:
```bash
/local-review                           # Review all changes since base branch
/local-review --uncommitted             # Only uncommitted changes
/local-review --since main              # Explicit base
/local-review --max-iterations 5        # Limit iterations
/local-review --files "src/**/*.py"     # Specific files only
/local-review --no-fix                  # Report only mode
```

---

## Phase 1: Initialize

**1. Parse arguments** from `$ARGUMENTS`

**2. Detect base reference** (if `--since` not provided):
```bash
# Try to find the merge-base with main/master
git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || { echo "⚠️ Warning: Could not find merge-base, using HEAD~10" >&2; echo "HEAD~10"; }
```

**3. Initialize tracking state**:
```
iteration = 0
max_iterations = <from args or 10>
commits_made = []
total_issues_fixed = 0
```

**4. Display configuration**:
```
## Review Configuration

**Base**: {base_ref}
**Scope**: {all changes | uncommitted only | specific files}
**Max iterations**: {max_iterations}
**Mode**: {fix & commit | fix only | report only}
```

---

## Phase 2: Review Loop

**For each iteration until clean or max reached:**

### Step 2.1: Gather Changes

```bash
# Get changed files
if --uncommitted:
    git diff --name-only
else:
    git diff --name-only {base_ref}..HEAD
    git diff --name-only  # Include uncommitted
fi

# Apply file filter if --files specified
# Filter to matching glob pattern
```

**If no changes**: Report "No changes to review" and exit.

### Step 2.2: Run Code Review

Dispatch a code review agent (uses `polymorphic-agent` with review-focused prompt):

```
Task(
  subagent_type="polymorphic-agent",
  description="Code review iteration {iteration+1}",
  prompt="You are reviewing code changes. Analyze the following for bugs, security issues, and code quality problems.

**Base ref**: {base_ref}
**Files to review**: {file_list}

Run: git diff {base_ref}..HEAD -- {files}

**Review Focus**:
- Critical: Security vulnerabilities, data loss, crashes
- Major: Logic errors, missing error handling, bugs
- Minor: Code style, unused imports, magic numbers

**Output Format**:
Return issues in this exact JSON format:
```json
{
  \"critical\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\"}],
  \"major\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\"}],
  \"minor\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\"}]
}
```

If no issues found, return: {\"critical\": [], \"major\": [], \"minor\": []}
"
)
```

**JSON Parsing Fallback**: If the agent returns malformed JSON or non-JSON response:
1. Try to extract issues from markdown/text format (look for `**file:line**` or `file.py:123` patterns)
2. If extraction succeeds, use extracted issues and continue normally
3. If extraction fails:
   - Log the raw response for debugging
   - Mark iteration as `PARSE_FAILED` (not "clean")
   - Display: "⚠️ Review response could not be parsed. Manual review required."
   - **Skip directly to Phase 3** (do NOT attempt fixes, do NOT continue loop)
4. On `PARSE_FAILED`, the final status MUST be "Parse failed - manual review needed" (never "Clean")

### Step 2.3: Display Issues

```markdown
## Review Iteration {iteration+1}

### Critical ({count})
- **{file}:{line}** - {description}

### Major ({count})
- **{file}:{line}** - {description}

### Minor ({count})
- **{file}:{line}** - {description}
```

**If no issues**: Increment iteration counter, then skip to Phase 3 (Final Summary)

**If `PARSE_FAILED`**: Increment iteration counter (a review was attempted), then skip to Phase 3

**If `--no-fix`**: Increment iteration counter (a review was performed), then skip to Phase 3

### Step 2.4: Fix Issues

For each severity level (critical first, then major, then minor):

```
Task(
  subagent_type="polymorphic-agent",
  description="Fix {severity} issues from review",
  prompt="Fix the following {severity} issues:

{issues_list}

**Instructions**:
1. Read each file
2. Apply the fix
3. Verify the fix doesn't break other code
4. Do NOT commit - just make the changes

**Files to modify**: {file_list}
"
)
```

### Step 2.5: Commit Fixes (if not `--no-commit`)

Group fixes by severity and commit:

```bash
# Stage fixed files
git add {fixed_files}

# Commit with descriptive message
git commit -m "fix(review): [{severity}] {summary}

- Fixed: {file}:{line} - {description}
- Fixed: {file}:{line} - {description}

Review iteration: {iteration+1}/{max_iterations}"
```

**Track commit**:
```
commits_made.append({
  "hash": git rev-parse --short HEAD,
  "severity": severity,
  "summary": summary,
  "issues_fixed": count
})
total_issues_fixed += count
```

**On commit failure**:
1. Log the error with failure reason (hooks, conflicts, permissions)
2. Leave files staged for manual intervention
3. Set `commit_failed = true` with reason
4. Increment iteration counter (a review cycle was attempted)
5. Exit to Phase 3 immediately (do NOT continue loop)
6. Final status: "Commit failed - {reason}. Files staged for manual review."

This prevents re-reviewing the same changes and gives the user clear next steps.

### Step 2.6: Check Loop Condition

```
iteration += 1

if iteration >= max_iterations:
    # Max iterations reached
    goto Phase 3
else:
    # Continue loop
    goto Step 2.1
```

---

## Phase 3: Final Summary

```markdown
## Review Complete

**Iterations**: {iteration}
**Total issues fixed**: {total_issues_fixed}
**Commits created**: {len(commits_made)}

### Commits
{for commit in commits_made:}
{index}. {commit.hash} - fix(review): [{commit.severity}] {commit.summary}
{end for}

**Status**: {status_indicator}
```

**Status indicators**:
- `Clean - Ready to push` (no issues on final review)
- `Max iterations reached - {n} issues remain` (hit limit)
- `Report only - {n} issues found` (--no-fix mode)
- `Changes staged - review before commit` (--no-commit mode)
- `Parse failed - manual review needed` (review response couldn't be parsed)
- `Commit failed - {reason}. Files staged for manual review.` (commit step failed)

---

## Implementation Notes

### Argument Parsing

Extract from `$ARGUMENTS` string:
```python
args = "$ARGUMENTS".split()
uncommitted = "--uncommitted" in args
no_fix = "--no-fix" in args
no_commit = "--no-commit" in args

# Extract --since value
if "--since" in args:
    idx = args.index("--since")
    since_ref = args[idx + 1] if idx + 1 < len(args) else None

# Extract --max-iterations value
if "--max-iterations" in args:
    idx = args.index("--max-iterations")
    try:
        max_iterations = int(args[idx + 1]) if idx + 1 < len(args) else 10
    except (ValueError, IndexError):
        print("⚠️ Warning: --max-iterations requires a numeric value. Using default (10).")
        max_iterations = 10

# Extract --files value
if "--files" in args:
    idx = args.index("--files")
    files_glob = args[idx + 1] if idx + 1 < len(args) else None
```

### Base Branch Detection

```bash
# Detect default branch
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
if [ -z "$DEFAULT_BRANCH" ]; then
    DEFAULT_BRANCH="main"
fi

# Find merge base
BASE_REF=$(git merge-base HEAD origin/$DEFAULT_BRANCH 2>/dev/null || { echo "⚠️ Warning: Using HEAD~10 fallback" >&2; echo "HEAD~10"; })
```

### Issue Severity Handling

**Critical issues**: Must be fixed immediately. Block further progress.

**Major issues**: Should be fixed. May require judgment on complexity.

**Minor issues**: Nice to fix. May be deferred if time-constrained.

### Commit Message Format

```
fix(review): [{severity}] {one-line summary}

{bullet list of fixes}

Review iteration: {current}/{max}
```

---

## Error Handling

| Error | Response |
|-------|----------|
| No git repo | "Error: Not in a git repository" |
| No changes | "No changes to review. Working tree clean." |
| Invalid --since ref | "Error: Invalid ref '{ref}'. Use branch name or commit SHA." |
| Review agent failure | Log error, mark iteration as PARSE_FAILED, require manual review |
| Fix agent failure | Log error, mark issue as "needs manual fix" |
| Malformed JSON response | Try text extraction; if fails, mark PARSE_FAILED (see Fallback) |
| Commit failure (general) | Log error, files remain staged for manual commit |
| Commit failure (hooks) | Report hook output, suggest `--no-verify` if appropriate |
| Commit failure (conflicts) | "Merge conflict detected - resolve manually before continuing" |
| Commit failure (permissions) | "Permission denied - check file permissions" |
| Stage failure (git add) | Log error, report which files couldn't be staged |

---

## Example Session

```
> /local-review --max-iterations 3

## Review Configuration

**Base**: abc1234 (origin/main)
**Scope**: All changes since base
**Max iterations**: 3
**Mode**: Fix & commit

---

## Review Iteration 1

### Critical (1)
- **src/api.py:45** - SQL injection in user query

### Major (2)
- **src/auth.py:89** - Missing password validation
- **src/utils.py:23** - Uncaught exception in parser

### Minor (3)
- **src/config.py:12** - Magic number should be constant
- **src/models.py:56** - Unused import
- **tests/test_api.py:78** - Test missing assertion

Fixing 6 issues...

Created commit: def5678 - fix(review): [critical] SQL injection vulnerability
Created commit: ghi9012 - fix(review): [major] Password validation and exception handling
Created commit: jkl3456 - fix(review): [minor] Code cleanup

---

## Review Iteration 2

### Critical (0)
### Major (0)
### Minor (0)

No issues found.

---

## Review Complete

**Iterations**: 2
**Total issues fixed**: 6
**Commits created**: 3

### Commits
1. def5678 - fix(review): [critical] SQL injection vulnerability
2. ghi9012 - fix(review): [major] Password validation and exception handling
3. jkl3456 - fix(review): [minor] Code cleanup

**Status**: Clean - Ready to push
```
