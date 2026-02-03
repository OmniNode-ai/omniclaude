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
# Try to find the merge-base with remote main/master
git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD origin/master 2>/dev/null || { echo "Warning: Could not find merge-base, using HEAD~10" >&2; echo "HEAD~10"; }
```

**3. Initialize tracking state**:
```
iteration = 0
max_iterations = <from args or 10>
commits_made = []
total_issues_fixed = 0
nit_count = 0  # Track deferred nits for final summary
failed_fixes = []  # Track {file, line, description} of issues that failed to fix (do not retry)
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

This step uses a two-step diff approach to capture all relevant changes:
1. Committed changes since base ref (for `--uncommitted=false`)
2. Uncommitted changes in working tree (always checked)

```bash
# Get changed files
if --uncommitted:
    files=$(git diff --name-only)
else:
    # Combine committed and uncommitted changes, then deduplicate
    committed=$(git diff --name-only {base_ref}..HEAD)
    uncommitted=$(git diff --name-only)
    files=$(echo -e "$committed\n$uncommitted" | sort -u | grep -v '^$')
fi

# Apply file filter if --files specified
# Filter to matching glob pattern
```

**If glob matches zero files** (when `--files` specified):
- Report "No files match pattern '{glob}'" and exit.

**If no changes**:
- If `iteration == 0` and `commits_made == []`: Report "No changes to review. Working tree clean." and exit.
- Otherwise: Skip to Phase 3 (show summary of work completed in previous iterations).

### Step 2.2: Run Code Review

Dispatch a `polymorphic-agent` with strict keyword-based classification (matching onex pr-review standards):

**IMPORTANT**: Always use `subagent_type="polymorphic-agent"` - do NOT use `feature-dev:code-reviewer` or other specialized review agents. The polymorphic-agent has ONEX capabilities and uses keyword-based classification (not confidence scoring).

```
Task(
  subagent_type="polymorphic-agent",
  description="Review iteration {iteration+1} changes",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent. Do NOT delegate to feature-dev:code-reviewer.

You are reviewing local code changes for production readiness.

## Changes to Review

**Base ref**: {base_ref}
**Files to review**: {file_list}
**Mode**: {--uncommitted | all changes}

# If --uncommitted mode:
Run: git diff -- {files}  # Only uncommitted changes

# If all changes mode (default):
Run: git diff {base_ref}..HEAD -- {files}  # Committed changes
Also run: git diff -- {files}  # Plus any uncommitted changes

Read each changed file fully to understand context.

## Priority Classification (Keyword-Based)

Classify issues using these keyword triggers (from onex pr-review):

### CRITICAL (Must Fix - BLOCKING)
Keywords: `security`, `vulnerability`, `injection`, `data loss`, `crash`, `breaking change`, `authentication bypass`, `authorization`, `secrets exposed`
- Security vulnerabilities (SQL injection, XSS, command injection)
- Data loss or corruption risks
- System crashes or unhandled exceptions that halt execution
- Breaking changes to public APIs

### MAJOR (Should Fix - BLOCKING)
Keywords: `bug`, `error`, `incorrect`, `wrong`, `fails`, `broken`, `performance`, `missing validation`, `race condition`, `memory leak`
- Logic errors that produce incorrect results
- Missing error handling for likely failure cases
- Performance problems (N+1 queries, unbounded loops)
- Missing or failing tests for critical paths
- Race conditions or concurrency bugs

### MINOR (Should Fix - BLOCKING)
Keywords: `should`, `missing`, `incomplete`, `edge case`, `documentation`
- Missing edge case handling
- Incomplete error messages
- Missing type hints on public APIs
- Code that works but violates project conventions (check CLAUDE.md)

### NIT (Optional - NOT blocking)
Keywords: `nit`, `consider`, `suggestion`, `optional`, `style`, `formatting`, `nitpick`
- Code style preferences
- Variable naming suggestions
- Minor refactoring opportunities
- Formatting inconsistencies

## Merge Requirements (STRICT)

Ready to merge ONLY when:
- ALL Critical issues resolved
- ALL Major issues resolved
- ALL Minor issues resolved
- Nits are OPTIONAL (nice to have)

NOT ready if ANY Critical/Major/Minor remain

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

**JSON Parsing and Validation**:
1. Parse the response as JSON
2. Validate structure: must have `critical`, `major`, `minor`, `nit` keys, each being an array
3. Validate each issue: must have `file` (string), `line` (number), `description` (string), `keyword` (string)
4. If validation fails, treat as malformed JSON (continue to fallback)

**Text Extraction Fallback**: If JSON parsing/validation fails:
1. Try to extract issues from markdown/text format using these patterns:
   - `**{file}:{line}** - {description}` (markdown bold format)
   - `{file}:{line}: {description}` (compiler-style format)
   - `- {file}:{line} - {description}` (list format)
2. Assign severity and keyword based on description content:
   - "critical/security/crash/injection/vulnerability" -> critical, keyword="extracted:critical"
   - "bug/error/logic/incorrect/fails/broken" -> major, keyword="extracted:major"
   - "nit/consider/suggestion/optional/style/formatting" -> nit, keyword="extracted:nit"
   - else -> minor, keyword="extracted:minor"
3. **If extraction succeeds** (finds at least one issue):
   - Use extracted issues and proceed normally to Step 2.3 (display issues)
4. **If extraction fails** (no recognizable patterns):
   - Log the raw response for debugging
   - Mark iteration as `PARSE_FAILED` (not "clean")
   - Display: "Warning: Review response could not be parsed. Manual review required."
   - Proceed to Step 2.3 where `PARSE_FAILED` triggers counter increment and exit to Phase 3
5. On `PARSE_FAILED`, the final status MUST be "Parse failed - manual review needed" (never "Clean")

**Agent Failure Handling**: If the review agent crashes, times out, or returns an error:
1. Log the error with details (timeout duration, error message, etc.)
2. Mark iteration as `AGENT_FAILED` (not "clean" or "parse failed")
3. Display: "Warning: Review agent failed: {error}. Manual review required."
4. **Continue to Step 2.3** (AGENT_FAILED will be handled there with counter increment)

### Step 2.3: Display Issues and Handle Error States

```markdown
## Review Iteration {iteration+1}

### CRITICAL ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### MAJOR ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### MINOR ({count}) - BLOCKING
- **{file}:{line}** - {description} [`{keyword}`]

### NIT ({count}) - Optional
- **{file}:{line}** - {description} [`{keyword}`]

**Merge Status**: {Ready | Blocked by N issues}
```

**Track nit count**: After parsing the review response, update `nit_count += len(issues["nit"])` for the final summary.

**Early Exit Conditions** (each increments counter before exiting):

**If no Critical/Major/Minor issues**:
```
iteration += 1  # A review iteration completed
goto Phase 3 (Final Summary)
```
- Nits alone do NOT block - they are optional

**If `PARSE_FAILED`**:
```
iteration += 1  # A review was attempted even though parsing failed
goto Phase 3
```

**If `AGENT_FAILED`**:
```
iteration += 1  # A review was attempted even though agent failed
goto Phase 3
```

**If `--no-fix`**:
```
iteration += 1  # A review was performed (report-only mode)
goto Phase 3
```

### Step 2.4: Fix Issues

**Pre-filter previously failed issues**:
```python
# Filter out issues that already failed in previous iterations (do not retry)
# Create set once for O(1) lookups instead of O(n*m) list comprehension
failed_fixes_set = {(f["file"], f["line"]) for f in failed_fixes}
for severity in ["critical", "major", "minor"]:
    issues[severity] = [
        issue for issue in issues[severity]
        if (issue["file"], issue["line"]) not in failed_fixes_set
    ]
```

For each severity level (critical first, then major, then minor), dispatch a `polymorphic-agent`:

**IMPORTANT**: Always use `subagent_type="polymorphic-agent"` for fixes - this ensures ONEX capabilities and proper observability.

```
Task(
  subagent_type="polymorphic-agent",
  description="Fix {severity} issues from review",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

Fix the following {severity} issues:

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

**Fix Agent Failure Handling**: If the fix agent crashes, times out, or fails:
1. Log the error with details
2. Add affected issues to `failed_fixes` list (do not retry in subsequent iterations):
   ```python
   for issue in affected_issues:
       failed_fixes.append({"file": issue.file, "line": issue.line, "description": issue.description})
   ```
3. Continue to next severity level (attempt remaining fixes)
4. If ALL fixes fail:
   ```
   iteration += 1  # A review cycle was attempted but all fixes failed
   goto Phase 3    # Status: "Fix failed - {n} issues need manual attention"
   ```
5. If SOME fixes succeed: proceed to Step 2.5 to commit successful fixes, note failed issues in commit message

### Step 2.5: Commit Fixes (if not `--no-commit`)

Group fixes by severity and commit.

**Note**: For multi-line commit messages, use heredoc format:
```bash
git commit -m "$(cat <<'EOF'
fix(review): [{severity}] {summary}

- Fixed: {file}:{line} - {description}
- Fixed: {file}:{line} - {description}

Review iteration: {iteration+1}/{max_iterations}
EOF
)"
```

```bash
# Stage fixed files and check for errors
git add {fixed_files}
if [ $? -ne 0 ]; then
    # Stage failed - increment counter and exit to Phase 3
    iteration += 1
    stage_failed = true
    goto Phase 3  # Status: "Stage failed - check file permissions"
fi

# Commit with descriptive message using heredoc (include failed fixes if any)
git commit -m "$(cat <<'EOF'
fix(review): [{severity}] {summary}

- Fixed: {file}:{line} - {description}
- Fixed: {file}:{line} - {description}
- FAILED: {file}:{line} - {description} (needs manual fix)

Review iteration: {iteration+1}/{max_iterations}
EOF
)"
```

**Track commit** (only count successfully fixed issues, not failed ones):
```
# count = number of successfully fixed issues (excludes items in failed_fixes)
commits_made.append({
  "hash": git rev-parse --short HEAD,
  "severity": severity,
  "summary": summary,
  "issues_fixed": count  # Excludes failed fixes
})
total_issues_fixed += count  # Only successfully fixed issues are counted
```

**On commit failure**:
1. Log the error with failure reason (hooks, conflicts, permissions)
2. Leave files staged for manual intervention
3. Set `commit_failed = true` with reason
4. Increment iteration counter and exit:
   ```
   iteration += 1  # A review cycle was attempted
   goto Phase 3
   ```
5. Final status: "Commit failed - {reason}. Files staged for manual review."

This prevents re-reviewing the same changes and gives the user clear next steps.

### Step 2.6: Check Loop Condition

**Note**: This step is ONLY reached in the normal flow (issues found -> fixed -> committed successfully).
Early exits (no issues, parse failed, no-fix mode, commit failed) have their own explicit
`iteration += 1` statements in Step 2.3 and Step 2.5 before jumping to Phase 3.

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
**Nits deferred**: {nit_count} (optional)

### Commits
{for index, commit in enumerate(commits_made):}
{index + 1}. {commit.hash} - fix(review): [{commit.severity}] {commit.summary}
{end for}

**Status**: {status_indicator}
```

**Status indicators**:
- `Clean - Ready to push` (no Critical/Major/Minor on final review; nits are OK)
- `Clean with nits - Ready to push` (only nits remain, which are optional)
- `Max iterations reached - {n} blocking issues remain` (hit limit with Critical/Major/Minor remaining)
- `Report only - {n} blocking issues found` (--no-fix mode)
- `Changes staged - review before commit` (--no-commit mode)
- `Parse failed - manual review needed` (review response couldn't be parsed)
- `Agent failed - {error}. Manual review required.` (review agent crashed/timed out)
- `Fix failed - {n} issues need manual attention` (all fix attempts failed in Step 2.4)
- `Stage failed - check file permissions` (git add failed)
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

# Extract --since value and validate
if "--since" in args:
    idx = args.index("--since")
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        print("Error: --since requires a ref argument")
        exit(1)
    since_ref = args[idx + 1]
    # Validate the ref exists
    if not git_rev_parse_verify(since_ref):  # git rev-parse --verify {since_ref} >/dev/null 2>&1
        print(f"Error: Invalid ref '{since_ref}'. Use branch name or commit SHA.")
        exit(1)

# Extract --max-iterations value
if "--max-iterations" in args:
    idx = args.index("--max-iterations")
    try:
        max_iterations = int(args[idx + 1]) if idx + 1 < len(args) else 10
        if max_iterations < 1:
            print("Warning: --max-iterations must be >= 1. Using default (10).")
            max_iterations = 10
    except (ValueError, IndexError):
        print("Warning: --max-iterations requires a numeric value. Using default (10).")
        max_iterations = 10

# Extract --files value
if "--files" in args:
    idx = args.index("--files")
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        print("Warning: --files requires a glob pattern. Reviewing all files.")
        files_glob = None
    else:
        files_glob = args[idx + 1]
```

### Base Branch Detection

```bash
# Detect default branch
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
if [ -z "$DEFAULT_BRANCH" ]; then
    DEFAULT_BRANCH="main"
fi

# Find merge base (with warning fallback for CI environments)
BASE_REF=$(git merge-base HEAD origin/$DEFAULT_BRANCH 2>/dev/null || { echo "Warning: Using HEAD~10 fallback" >&2; echo "HEAD~10"; })
```

### Issue Severity Handling (Strict Mode)

**CRITICAL issues**: MUST be fixed. BLOCKING - cannot merge.

**MAJOR issues**: MUST be fixed. BLOCKING - cannot merge.

**MINOR issues**: MUST be fixed. BLOCKING - cannot merge.

**NIT issues**: Optional. NOT blocking - can merge with nits remaining.

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
| Review agent failure | Log error, mark iteration as `AGENT_FAILED`, increment counter via Step 2.3, then exit to Phase 3 with status "Agent failed - {error}. Manual review required." |
| Fix agent failure | Log error, mark issue as "needs manual fix" |
| Malformed JSON response | Try text extraction; if fails, mark `PARSE_FAILED` (see Fallback) |
| Commit failure (general) | Log error, increment counter, files remain staged, exit to Phase 3 |
| Commit failure (hooks) | Report hook output, increment counter, suggest `--no-verify`, exit to Phase 3 |
| Commit failure (conflicts) | Log "Merge conflict detected", increment counter, exit to Phase 3 |
| Commit failure (permissions) | Log "Permission denied", increment counter, exit to Phase 3 |
| Stage failure (git add) | Log error, report which files couldn't be staged, increment counter, exit to Phase 3 with status "Stage failed - check file permissions" |

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

### CRITICAL (1) - BLOCKING
- **src/api.py:45** - SQL injection in user query [`injection`]

### MAJOR (2) - BLOCKING
- **src/auth.py:89** - Missing password validation [`missing validation`]
- **src/utils.py:23** - Uncaught exception in parser [`error`]

### MINOR (1) - BLOCKING
- **src/config.py:12** - Magic number should be constant [`should`]

### NIT (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: Blocked by 4 issues (1 critical, 2 major, 1 minor)

Fixing 4 blocking issues (nits deferred)...

Created commit: def5678 - fix(review): [critical] SQL injection vulnerability
Created commit: ghi9012 - fix(review): [major] Password validation and exception handling
Created commit: jkl3456 - fix(review): [minor] Magic number extracted to constant

---

## Review Iteration 2

### CRITICAL (0)
### MAJOR (0)
### MINOR (0)
### NIT (2) - Optional
- **src/models.py:56** - Unused import [`style`]
- **tests/test_api.py:78** - Consider adding assertion message [`suggestion`]

**Merge Status**: Ready (only optional nits remain)

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

**Status**: Clean with nits - Ready to push
```
