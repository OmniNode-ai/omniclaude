---
name: pr-review-dev
description: PR Dev Review - Fix Critical/Major/Minor Issues (PR Review + CI Failures)
version: 1.0.0
category: workflow
tags:
  - pr
  - review
  - ci
  - code-quality
author: OmniClaude Team
args:
  - name: pr_url
    description: PR URL or number (auto-detects from branch)
    required: false
  - name: --no-ci
    description: Skip CI failure analysis
    required: false
  - name: --ci-only
    description: Only analyze CI failures
    required: false
  - name: --hide-resolved
    description: Hide resolved review comments
    required: false
  - name: --show-resolved-only
    description: Only show resolved comments
    required: false
---

# PR Dev Review - Fix Critical/Major/Minor Issues (PR Review + CI Failures)

**Workflow**: Fetch PR issues -> Fetch CI failures -> Combine -> **AUTO-RUN** parallel-solve (non-nits) -> Ask about nitpicks

**Announce at start:** "I'm using the pr-review-dev skill to review and fix PR issues."

## Quick Start (Fully Automated)

1. **Fetch and collate all issues** (PR review + CI failures):
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues-with-ci "${1:-}" 2>&1
   ```

2. **Automatically dispatch parallel-solve** with the collated output (excluding NITPICK sections)

3. **Ask about nitpicks** after parallel-solve completes

## Dispatch Contracts (Execution-Critical)

You are an orchestrator. You gather and collate issues, then dispatch parallel-solve.
You do NOT fix issues yourself.

**Rule: NEVER call Edit() or Write() to fix PR issues.**

### Gather Phase -- inline (MCP + gh operations)

Fetch PR review comments and CI failure logs. No dispatch needed.

### Collate Phase -- inline

Merge issues into severity-classified list: CRITICAL -> MAJOR -> MINOR -> NIT.
Filter nitpicks by default.

### Fix Phase -- dispatch via parallel-solve

```
Skill(skill="onex:parallel-solve")
```

> **Note**: The `onex:` prefix is required for both `Skill(skill=...)` calls AND `subagent_type=` in Task() calls.

Pass collated issues as context.

### Nit Phase -- ask user

After fixes complete, offer to fix deferred nitpicks.

---

## Detailed Workflow

### Step 1: Fetch PR Review Issues

Execute the collate-issues helper to get PR review issues in parallel-solve-ready format:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format 2>&1
```

**Save this output** - it is needed for Step 3.

#### Resolution Filtering Options

The collate-issues command supports filtering issues by their resolution status:

| Flag | Behavior |
|------|----------|
| *(default)* | Shows all issues (resolved + open) |
| `--hide-resolved` | Only show open issues (excludes resolved/outdated) |
| `--show-resolved-only` | Only show resolved issues (for verification) |

**Resolution Indicators** (when shown):
- `[RESOLVED]` - Thread was manually marked as resolved on GitHub
- `[OUTDATED]` - Code has changed since the comment was made (position no longer valid)

**Examples with resolution filtering**:
```bash
# Default: show all issues
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format

# Only show open issues (recommended for fixing)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format --hide-resolved

# Only show resolved issues (for verification)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --show-resolved-only
```

**When to use each**:
- **Default**: First pass to see everything
- **`--hide-resolved`**: Focus on remaining work (exclude already-addressed issues)
- **`--show-resolved-only`**: Verify which issues have been marked resolved

---

### Step 2: Fetch CI Failures

Execute the ci-quick-review helper to get CI failure data in JSON format:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --json "${1:-}" 2>&1
```

**What this returns**:
- JSON with `summary` (counts by severity) and `failures` array
- Exit code 0: CI failures found
- Exit code 1: Error fetching data
- Exit code 2: No CI failures (success!)

**Handle the response**:
- If exit code 2 -> Skip to Step 3 (no CI failures to fix)
- If exit code 1 -> Report error and skip to Step 3 (continue with PR review issues only)
- If exit code 0 -> Parse JSON and proceed to Step 2.5

---

### Step 2.5: Parse and Format CI Failures

If CI failures were found (exit code 0), parse the JSON and format for parallel-solve:

```
# Extract from JSON:
#   - summary.critical, summary.major, summary.minor
#   - failures[].workflow, failures[].job, failures[].step, failures[].severity
#
# Format as severity-grouped list with [Workflow:Job:Step] prefixes
```

**Example formatted output**:
```
CRITICAL (CI Failures):
- [CI/CD:Build:Run Tests] ModuleNotFoundError: No module named 'pydantic'
- [CI/CD:Lint:Ruff Check] F401 'os' imported but unused

MAJOR (CI Failures):
- [CI/CD:Type Check:Mypy] error: Incompatible types in assignment

MINOR (CI Failures):
- [Deploy:Bundle:Size Check] Bundle size exceeds recommendation
```

---

### Step 3: Combine and Fire Parallel-Solve

**Combine the outputs from Step 1 and Step 2.5**, grouping by severity:

1. Take PR review issues from Step 1
2. Take CI failures from Step 2.5 (if any)
3. Combine under each severity heading (CRITICAL, MAJOR, MINOR)
4. **EXCLUDE any NITPICK sections** from Step 1

**Example combined output**:
```
Fix all PR #33 issues (PR review + CI failures):

CRITICAL:
- [file.py:123] SQL injection vulnerability (PR Review)
- [config.py:45] Missing environment variable validation (PR Review)
- [CI/CD:Build:Compile] ModuleNotFoundError: No module named 'pydantic' (CI Failure)

MAJOR:
- [helper.py:67] Missing error handling (PR Review)
- [CI/CD:Lint:Ruff] F401 'os' imported but unused (CI Failure)

MINOR:
- [docs.md:12] Missing documentation (PR Review)
- [Deploy:Bundle:Size] Bundle size warning (CI Failure)
```

**IMPORTANT**: Do NOT include the NITPICK section in the parallel-solve dispatch.

---

### Step 4: Ask About Nitpicks

After parallel-solve completes, check the **Step 1 output** for any NITPICK sections:

- If nitpicks were found in the original collate-issues output, ask the user:
  "Critical/major/minor issues (PR review + CI failures) are being addressed. There are [N] nitpick items from the PR review. Address them now?"

- If yes -> Fire another parallel-solve with just the nitpick items from the Step 1 output.

**Note**: Nitpicks are discovered from the Step 1 collate-issues output but excluded from Step 3's parallel-solve dispatch.

---

## Quick Reference

**Automated Approach** (Recommended):

Use the unified helper script that combines both PR review issues and CI failures automatically:

```bash
# Combines PR review + CI failures in one command
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues-with-ci "${1:-}" 2>&1
```

This script:
- Automatically fetches PR review issues (Step 1)
- Automatically fetches CI failures (Step 2)
- Parses and formats CI failures (Step 2.5)
- Combines both by severity (Step 3)
- Outputs ready-to-use parallel-solve format
- Gracefully handles CI fetch failures (continues with PR review only)

**Manual Approach** (if you need finer control):

```bash
# Step 1: PR review issues (all issues)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format

# Step 1 (alt): PR review issues (only open issues - recommended)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format --hide-resolved

# Step 1 (alt): PR review issues (only resolved - for verification)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --show-resolved-only

# Step 2: CI failures (JSON)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --json "${1:-}"

# Step 2 (alternative): CI failures (human-readable)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review "${1:-}"
```

**Resolution Filtering** (collate-issues):
- *(default)* = Show all issues (resolved + open)
- `--hide-resolved` = Only open issues (use when fixing remaining work)
- `--show-resolved-only` = Only resolved issues (use to verify addressed items)

**Exit Codes** (ci-quick-review):
- 0 = CI failures found (parse and include)
- 1 = Error fetching data (skip CI, continue with PR review only)
- 2 = No CI failures (skip CI, continue with PR review only)

**Format**: Location prefixes for clarity
- PR Review: `[file.py:123]` or just description
- PR Review (resolved): `[RESOLVED]` or `[OUTDATED]` prefix indicates status
- CI Failures: `[Workflow:Job:Step]` for traceability
