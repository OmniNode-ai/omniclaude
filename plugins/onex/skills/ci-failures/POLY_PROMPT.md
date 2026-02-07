# CI Failures — Poly Worker Prompt

You are analyzing CI/CD failures for a GitHub PR or branch. Provide a concise summary with severity classification and actionable guidance.

## Arguments

- `PR_OR_BRANCH`: PR number or branch name (provided by orchestrator)
- `WORKFLOW_FILTER`: Optional workflow name filter

## Steps

### 1. Determine Target

If a PR number was provided, use it directly. Otherwise, determine the current branch and find the associated PR.

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
PR_NUMBER=$(gh pr list --head "$BRANCH" --json number --jq '.[0].number' 2>/dev/null)
```

### 2. Fetch CI Failure Summary

Use the `ci-quick-review` script for a concise summary (~20-50 lines):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review "${PR_OR_BRANCH}" 2>&1
```

**What ci-quick-review provides**:
- Concise summary of all failed workflows, jobs, and steps
- Severity classification (CRITICAL/MAJOR/MINOR)
- Error pattern recognition (known patterns vs unrecognized)
- Quick actionable guidance
- Technology context (Python, FastAPI, Django, etc.)

### 3. Analyze Summary Output

Review the output and categorize:

**CRITICAL** (Blocking deployment):
- Build failures, compilation errors, missing dependencies, infrastructure failures

**MAJOR** (Must fix):
- Test failures, linting errors, type check failures, security vulnerabilities

**MINOR** (Should fix):
- Warnings, code quality issues, documentation generation failures

### 4. Deep-Dive Investigation (Optional)

For detailed investigation of specific failures, use the two-tier approach:

**Tier 1**: `ci-quick-review` (this command) - Quick summary (~20-50 lines)
**Tier 2**: `get-ci-job-details` - Deep-dive with logs and web research

Only use Tier 2 when error messages are unclear, you need full logs, or unrecognized errors require web research.

### 5. Provide Actionable Output

Summarize findings with:
- **Total Failures**: Count by severity (CRITICAL/MAJOR/MINOR)
- **Key Issues**: Highlight the most critical problems
- **Quick Fixes**: Immediate actions to resolve common issues
- **Merge Status**: Whether the PR is ready to merge or not

## Output Format

```
=== CI Failures Quick Review ===
PR: #NNN (branch: branch-name)
Total Failures: N

🔴 CRITICAL FAILURES (N)
1. Description
   Error: ...
   Quick Fix: ...

🟠 MAJOR FAILURES (N)
...

🟡 MINOR FAILURES (N)
...

=== Summary ===
Status: ❌/✅ merge readiness
```

## Error Handling

- If no PR found: report "No PR found for current branch"
- If no CI runs: report "No CI runs found"
- If script fails: fall back to `gh run list` direct query
