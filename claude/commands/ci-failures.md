# CI Failures Command - Quick Review

Check GitHub Actions CI failures for the current PR or branch and provide a concise summary of issues (~20-50 lines instead of 624).

## Task

Analyze CI/CD failures and provide a quick summary of issues with severity classification and actionable guidance.

## Steps

### 1. Determine Target

If the user provided a PR number as argument `$1`, use that. Otherwise, determine the current branch and find associated PR.

```bash
# Get current branch if no PR number provided
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

# Find PR number for current branch
PR_NUMBER=$(gh pr list --head "$BRANCH" --json number --jq '.[0].number' 2>/dev/null)
```

### 2. Fetch CI Failure Summary

Use the `ci-quick-review` script which provides a concise summary of CI failures:

```bash
# Fetch concise CI failure summary (~20-50 lines instead of 624)
~/.claude/skills/ci-failures/ci-quick-review "${1:-$PR_NUMBER}" 2>&1
```

**What ci-quick-review provides**:
- Concise summary of all failed workflows, jobs, and steps
- Severity classification (CRITICAL/MAJOR/MINOR)
- Error pattern recognition (known patterns vs unrecognized)
- Quick actionable guidance
- Technology context (Python, FastAPI, Django, etc.)
- Output: ~20-50 lines (vs 624 lines from fetch-ci-data)

### 3. Analyze Summary Output

The `ci-quick-review` script provides a concise summary that's immediately actionable. Review the output for:

**🔴 CRITICAL** (Blocking deployment):
- Build failures
- Compilation errors
- Missing dependencies
- Infrastructure failures

**🟠 MAJOR** (Must fix):
- Test failures
- Linting errors
- Type check failures
- Security vulnerabilities

**🟡 MINOR** (Should fix):
- Warnings
- Code quality issues
- Documentation generation failures

### 4. Deep-Dive Investigation (Optional)

For detailed investigation of specific failures, use the two-tier approach:

**Tier 1**: `ci-quick-review` (this command) - Quick summary (~20-50 lines)
**Tier 2**: `get-ci-job-details` (future command) - Deep-dive with logs and web research

The quick review is sufficient for most cases. Use the detailed investigation only when:
- Error messages are unclear from the summary
- You need full logs and stack traces
- Unrecognized errors require web research

### 5. Provide Actionable Output

Summarize the findings from `ci-quick-review` output with:
- **Total Failures**: Count by severity (CRITICAL/MAJOR/MINOR)
- **Key Issues**: Highlight the most critical problems
- **Quick Fixes**: Immediate actions to resolve common issues
- **Merge Status**: Whether the PR is ready to merge or not

## Example Usage

```bash
# Check current branch CI failures
/ci-failures

# Check specific PR
/ci-failures 123

# With workflow filter (if supported by script)
/ci-failures 123 "CI/CD"
```

## Arguments

- `$1` (optional): PR number (defaults to current branch's PR)
- `$2` (optional): Workflow name filter (e.g., "CI/CD", "Tests", "Lint")

## Expected Output Format

```
=== CI Failures Quick Review ===
PR: #123 (branch: feature/my-branch)
Timestamp: 2025-11-23 14:30:00
Total Failures: 5

🔴 CRITICAL FAILURES (2)

1. Build Failure - CI/CD Workflow
   Error: ModuleNotFoundError: No module named 'pydantic'
   Quick Fix: Add pydantic to pyproject.toml → poetry add pydantic
   Logs: https://github.com/user/repo/actions/runs/12345

2. Custom Validation - FastAPI Build
   Error: Custom validation failed (unrecognized pattern)
   Context: Python FastAPI
   Quick Fix: Check Pydantic validators or use /get-ci-job-details for investigation
   Logs: https://github.com/user/repo/actions/runs/12346

🟠 MAJOR FAILURES (3)

3. Test Suite Failed - Python Tests
   Error: ConnectionRefusedError: [Errno 111] Connection refused
   Quick Fix: Verify Kafka service in CI (check docker-compose.yml)
   Logs: https://github.com/user/repo/actions/runs/12347

4. Linting Failed - Ruff Check
   Error: F401 'os' imported but unused (src/main.py:42:1)
   Quick Fix: Remove unused import → ruff check --fix src/main.py
   Logs: https://github.com/user/repo/actions/runs/12348

5. Type Check Failed - MyPy
   Error: Incompatible return value type (src/config.py:15)
   Quick Fix: Fix return type annotation or return value
   Logs: https://github.com/user/repo/actions/runs/12349

=== Summary ===
Total Failures: 5
Critical: 2 (must fix before merge)
Major: 3 (must fix before merge)
Minor: 0

Status: ❌ Cannot merge - Critical and Major issues must be resolved

💡 Tip: For detailed investigation, use /get-ci-job-details <job-id>
```

## Implementation Notes

### Two-Tier Approach

**Tier 1: ci-quick-review** (this command):
- Provides concise summary (~20-50 lines vs 624 lines)
- Sufficient for 80% of CI debugging scenarios
- Quick actionable guidance without verbose logs
- Error classification and severity ranking
- Use this for initial triage and common issues

**Tier 2: get-ci-job-details** (future command):
- Deep-dive investigation with full logs
- Web research for unrecognized errors
- Detailed stack traces and context
- Use when quick review is insufficient

### Core Workflow
- Use `~/.claude/skills/ci-failures/ci-quick-review` script (not `fetch-ci-data`)
- Script automatically classifies errors as recognized vs unrecognized
- Provides quick actionable guidance for common patterns
- Includes technology context (Python, FastAPI, etc.)

### Error Recognition Patterns
**Recognized** (quick fix guidance provided):
- pytest/unittest test failures
- mypy/pyright type checking errors
- ruff/flake8/pylint linting errors
- black/prettier formatting issues
- Docker build errors
- npm/yarn/pip package manager errors
- Standard CI setup/checkout/cache steps

**Unrecognized** (may need Tier 2 investigation):
- Custom build steps
- Proprietary validation tools
- Unknown compilation errors
- Environment-specific failures
- Custom CI scripts
- Infrastructure failures without clear patterns

### Performance Optimization
- **Quick review**: ~2-5 seconds total (no web research)
- **Concise output**: 20-50 lines (vs 624 lines from fetch-ci-data)
- **Cache**: Results cached with 5-minute TTL
- **Fallback**: Use Tier 2 (get-ci-job-details) for deep investigation

### Output Requirements
- Categorize by severity (CRITICAL/MAJOR/MINOR)
- Mark recognized vs unrecognized errors
- Provide quick fix guidance for recognized errors
- Suggest Tier 2 investigation for unrecognized errors
- Provide direct links to full logs
- Support both PR number and branch-based lookups
- Handle cases where no CI failures exist (success message)

## Success Criteria

- ✅ All failed workflows are identified
- ✅ Errors are categorized by severity (CRITICAL/MAJOR/MINOR)
- ✅ Recognized vs unrecognized errors are clearly marked
- ✅ Each failure includes quick fix guidance
- ✅ Links to full GitHub Actions logs are provided
- ✅ Summary shows total failures by severity
- ✅ Clear merge readiness status is shown
- ✅ Output is concise (~20-50 lines instead of 624)
- ✅ Two-tier approach mentioned for deep investigation

## Performance Targets

- **Quick review**: ~2-5 seconds total
- **Output size**: 20-50 lines (vs 624 lines from fetch-ci-data)
- **Cache hit**: <100ms for repeated analysis (within 5-minute TTL)
- **Sufficient for**: 80% of CI debugging scenarios
