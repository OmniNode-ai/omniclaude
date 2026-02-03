---
name: local-review
description: Local code review loop that iterates through review, fix, commit cycles without pushing
tags: [review, code-quality, local, iteration]
---

# /local-review - Local Code Review Loop

Review local changes, fix issues, commit fixes, and iterate until clean or max iterations reached.

**Workflow**: Gather changes → Review → Fix → Commit → Repeat until clean

> **Classification System**: Uses onex pr-review keyword-based classification (not confidence scoring).
> ALL Critical/Major/Minor issues MUST be resolved. Only Nits are optional.
> See: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md` for full priority definitions.

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
git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || echo "HEAD~10"
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

Dispatch a `polymorphic-agent` with strict keyword-based classification (matching onex pr-review standards):

```
Task(
  subagent_type="polymorphic-agent",
  description="Review iteration {iteration+1} changes",
  prompt="You are reviewing local code changes for production readiness.

## Changes to Review

**Base ref**: {base_ref}
**Files to review**: {file_list}

Run: git diff {base_ref}..HEAD -- {files}

Read each changed file fully to understand context.

## Priority Classification (Keyword-Based)

Classify issues using these keyword triggers (from onex pr-review):

### 🔴 CRITICAL (Must Fix - BLOCKING)
Keywords: `security`, `vulnerability`, `injection`, `data loss`, `crash`, `breaking change`, `authentication bypass`, `authorization`, `secrets exposed`
- Security vulnerabilities (SQL injection, XSS, command injection)
- Data loss or corruption risks
- System crashes or unhandled exceptions that halt execution
- Breaking changes to public APIs

### 🟠 MAJOR (Should Fix - BLOCKING)
Keywords: `bug`, `error`, `incorrect`, `wrong`, `fails`, `broken`, `performance`, `missing validation`, `race condition`, `memory leak`
- Logic errors that produce incorrect results
- Missing error handling for likely failure cases
- Performance problems (N+1 queries, unbounded loops)
- Missing or failing tests for critical paths
- Race conditions or concurrency bugs

### 🟡 MINOR (Should Fix - BLOCKING)
Keywords: `should`, `missing`, `incomplete`, `edge case`, `documentation`
- Missing edge case handling
- Incomplete error messages
- Missing type hints on public APIs
- Code that works but violates project conventions (check CLAUDE.md)

### ⚪ NIT (Optional - NOT blocking)
Keywords: `nit`, `consider`, `suggestion`, `optional`, `style`, `formatting`, `nitpick`
- Code style preferences
- Variable naming suggestions
- Minor refactoring opportunities
- Formatting inconsistencies

## Merge Requirements (STRICT)

✅ **Ready to merge ONLY when**:
- ALL Critical issues resolved
- ALL Major issues resolved
- ALL Minor issues resolved
- Nits are OPTIONAL (nice to have)

❌ **NOT ready if ANY Critical/Major/Minor remain**

## Output Format

Return issues in this exact JSON format:
```json
{
  \"critical\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
  \"major\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
  \"minor\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
  \"nit\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}]
}
```

**Rules**:
- Be specific: include file:line references
- Explain WHY each issue matters
- Include the keyword that triggered classification
- Do NOT mark nitpicks as Critical/Major/Minor
- Do NOT use confidence scoring - use keyword classification only

If no issues found, return: {\"critical\": [], \"major\": [], \"minor\": [], \"nit\": []}
"
)
```

### Step 2.3: Display Issues

```markdown
## Review Iteration {iteration+1}

### 🔴 Critical ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### 🟠 Major ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### 🟡 Minor ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### ⚪ Nit ({count}) - Optional
- **{file}:{line}** - {description} [`{keyword}`]

**Merge Status**: {✅ Ready | ❌ Blocked by N issues}
```

**If no Critical/Major/Minor issues**: Skip to Phase 3 (Final Summary)
- Nits alone do NOT block - they are optional

**If `--no-fix`**: Display issues and skip to Phase 3

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

### Step 2.5: Stage and Commit Fixes

**Always stage fixes** (regardless of `--no-commit`):

```bash
# Stage fixed files
git add {fixed_files}
```

**Track issues fixed** (regardless of `--no-commit`):
```
total_issues_fixed += count
```

**Commit** (if not `--no-commit`):

```bash
# Commit with descriptive message
git commit -m "fix(review): [{severity}] {summary}

- Fixed: {file}:{line} - {description}
- Fixed: {file}:{line} - {description}

Review iteration: {iteration+1}/{max_iterations}"
```

**Track commit** (only when committing):
```
commits_made.append({
  "hash": git rev-parse --short HEAD,
  "severity": severity,
  "summary": summary,
  "issues_fixed": count
})
```

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

**Status indicators** (choose based on total_issues_fixed and mode):
- `✅ Clean - No issues found` (no Critical/Major/Minor on first review, 0 issues fixed)
- `✅ Clean - Ready to push` (all issues fixed and committed)
- `⚪ Clean with nits - No changes needed` (only nits found, 0 issues fixed)
- `⚪ Clean with nits - Ready to push` (blocking issues fixed and committed, nits remain)
- `❌ Max iterations reached - {n} blocking issues remain` (hit limit with Critical/Major/Minor remaining)
- `📋 Report only - {n} blocking issues found` (--no-fix mode)
- `📝 Changes staged - review before commit` (--no-commit mode, issues were fixed but not committed)

**Status selection logic**:
```
if --no-fix:
    "📋 Report only - {n} blocking issues found"
elif blocking_issues_remain:
    "❌ Max iterations reached - {n} blocking issues remain"
elif total_issues_fixed == 0:
    # No blocking issues found to fix (only nits which are optional)
    if nits_remain:
        "⚪ Clean with nits - No changes needed"
    else:
        "✅ Clean - No issues found"
elif --no-commit:
    # Issues were fixed but not committed (staged only)
    "📝 Changes staged - review before commit"
elif nits_remain:
    "⚪ Clean with nits - Ready to push"
else:
    "✅ Clean - Ready to push"
```

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
    max_iterations = int(args[idx + 1]) if idx + 1 < len(args) else 10

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
BASE_REF=$(git merge-base HEAD origin/$DEFAULT_BRANCH 2>/dev/null || echo "HEAD~10")
```

### Issue Severity Handling (Strict Mode)

**🔴 Critical issues**: MUST be fixed. BLOCKING - cannot merge.

**🟠 Major issues**: MUST be fixed. BLOCKING - cannot merge.

**🟡 Minor issues**: MUST be fixed. BLOCKING - cannot merge.

**⚪ Nit issues**: Optional. NOT blocking - can merge with nits remaining.

**This matches the onex pr-review merge requirements**: ALL Critical/Major/Minor must be resolved before merge. Only nits are optional.

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
| Review agent failure | Log error, continue with partial results |
| Fix agent failure | Log error, mark issue as "needs manual fix" |
| Commit failure | Log error, continue (files remain staged) |

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

### 🔴 Critical (1) - BLOCKING
- **src/api.py:45** - SQL injection in user query [`injection`]

### 🟠 Major (2) - BLOCKING
- **src/auth.py:89** - Missing password validation [`missing validation`]
- **src/utils.py:23** - Uncaught exception in parser [`error`]

### 🟡 Minor (1) - BLOCKING
- **src/config.py:12** - Magic number should be constant [`should`]

### ⚪ Nit (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: ❌ Blocked by 4 issues (1 critical, 2 major, 1 minor)

Fixing 4 blocking issues (nits deferred)...

Created commit: def5678 - fix(review): [critical] SQL injection vulnerability
Created commit: ghi9012 - fix(review): [major] Password validation and exception handling
Created commit: jkl3456 - fix(review): [minor] Magic number extracted to constant

---

## Review Iteration 2

### 🔴 Critical (0)
### 🟠 Major (0)
### 🟡 Minor (0)
### ⚪ Nit (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: ✅ Ready (only optional nits remain)

---

## Review Complete

**Iterations**: 2
**Total issues fixed**: 4
**Commits created**: 3
**Nits deferred**: 2 (optional)

### Commits
1. def5678 - fix(review): [critical] SQL injection vulnerability
2. ghi9012 - fix(review): [major] Password validation and exception handling
3. jkl3456 - fix(review): [minor] Magic number extracted to constant

**Status**: ⚪ Clean with nits - Ready to push
```
