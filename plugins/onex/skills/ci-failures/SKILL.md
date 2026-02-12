---
name: ci-failures
description: Fetch and analyze GitHub Actions CI failures for debugging
version: 1.0.0
category: development
tags:
  - github
  - ci
  - debugging
  - workflow
  - actions
author: OmniClaude Team
dependencies:
  - gh (GitHub CLI)
  - jq (JSON processor)
---

# CI Failures Analysis

Production-ready CI/CD debugging system that fetches GitHub Actions workflow runs, analyzes failures, and provides actionable debugging information with severity classification.

## 🚨 CRITICAL: ALWAYS DISPATCH TO POLYMORPHIC AGENT

**DO NOT run bash scripts directly.** When this skill is invoked, you MUST dispatch to a polymorphic-agent.

### ❌ WRONG - Running bash directly:
```
Bash(${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33)
Bash(${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33)
```

### ✅ CORRECT - Dispatch to polymorphic-agent:
```
Task(
  subagent_type="polymorphic-agent",
  description="CI failure analysis for PR #33",
  prompt="Analyze CI failures for PR #33. Use the ci-failures skill tools:
    1. Run: ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33
    2. For deep investigation, use: ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details <job_id>
    3. Analyze the failures and categorize by severity

    Available tools in ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/:
    - ci-quick-review <PR#> - Quick summary of all failures (Tier 1)
    - get-ci-job-details <job_id> - Deep dive into specific job (Tier 2)
    - fetch-ci-data <PR#> - Raw CI data in JSON format

    Return a summary with:
    - Severity breakdown (CRITICAL/MAJOR/MINOR)
    - Root cause analysis
    - Suggested fixes for each failure
    - Whether the PR is blocked from merge"
)
```

**WHY**: Polymorphic agents have full ONEX capabilities, intelligence integration, quality gates, and proper observability. Running bash directly bypasses all of this.

## Skills Available

1. **ci-quick-review** - One-command CI failure summary with actionable suggestions (RECOMMENDED - Tier 1)
2. **get-ci-job-details** - Deep-dive investigation into specific CI job failures (Tier 2)
3. **fetch-ci-data** - Fetch all CI failures from GitHub Actions workflows with severity classification

## Overview

The CI Failures skill provides comprehensive analysis of GitHub Actions workflow failures, including:
- Workflow run status and timing
- Failed job identification
- Step-level error extraction
- Log analysis with context
- Severity classification (CRITICAL/MAJOR/MINOR)
- Root cause suggestions
- Retry recommendations

## Features

### Workflow Run Fetching
- ✅ Fetch latest workflow runs for a branch
- ✅ Filter by workflow status (failure, success, cancelled)
- ✅ Retrieve specific run by ID
- ✅ Include timing and duration metrics

### Job Analysis
- ✅ Identify all failed jobs in a workflow run
- ✅ Extract step-level failures
- ✅ Capture error messages and stack traces
- ✅ Include log context (5 lines before/after)

### Error Classification
- ✅ Severity classification (CRITICAL/MAJOR/MINOR)
- ✅ Pattern detection (test failures, build errors, timeout, etc.)
- ✅ Flaky test identification
- ✅ Root cause suggestions

### Performance Metrics
- ✅ Job duration tracking
- ✅ Timeout detection
- ✅ Resource usage analysis
- ✅ Historical failure rate

## Usage

> **📁 Temporary Files**: Always use repository-local `./tmp/` directory for temporary files.
> Never use system `/tmp/` - this violates the repository pattern established in PR #36.
> All examples below correctly use `{REPO}/tmp/` for output files.

### Quick Review (RECOMMENDED)

**Single command for most use cases** - fetches CI failures and displays a concise summary:

```bash
# Quick review of current branch
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review

# Review specific PR
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33

# Review specific branch
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review my-feature-branch

# Filter to specific workflow
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --workflow ci-cd 33

# JSON output for scripting
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --json 33 > ./tmp/ci-failures.json
```

**Benefits**:
- ✅ Single command (no need to chain fetch + analyze)
- ✅ Smart defaults (auto-saves to tmp/)
- ✅ Auto-displays output in terminal
- ✅ Fewer agent actions needed

### Get CI Job Details (Tier 2 - Deep Dive)

**Deep-dive investigation into specific CI job failures** - complements ci-quick-review by providing complete logs, error traces, and context for a single job.

```bash
# By job ID
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details 56174634733

# By job URL (automatically extracts job ID)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details https://github.com/user/repo/actions/runs/123/job/456

# With PR number for additional context
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details 56174634733 33

# Get job ID from ci-quick-review output, then investigate
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details <job_id_from_output>
```

**When to Use**:
- After running `ci-quick-review` to identify problem jobs
- When you need complete error logs and stack traces
- For investigating flaky tests or intermittent failures
- When suggested fixes from quick review aren't sufficient
- To see exact error context (5-10 lines before/after)

**Output Includes**:
- ✅ Complete job logs (full text output)
- ✅ Job metadata (timing, status, steps)
- ✅ Failed step details with error highlighting
- ✅ Stack traces (Python, JavaScript, etc.) formatted clearly
- ✅ Related jobs in same workflow run
- ✅ Suggested fixes based on error patterns
- ✅ GitHub links for further investigation

**Workflow** (Two-Tier Approach):
1. **Tier 1**: Run `ci-quick-review` to see summary of all failures
2. **Tier 2**: For each critical/major failure, run `get-ci-job-details <job_id>` for deep investigation

**Cache**: Job details cached for 5 minutes (same as other CI skills)

### Fetch CI Data (Advanced)

```bash
# Fetch CI failures for PR #33
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33

# Fetch for specific branch
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data my-feature-branch

# Fetch for current branch
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data

# Filter to specific workflow
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data --workflow enhanced-ci 33

# Bypass cache (force fresh fetch)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data --no-cache 33
```

**Output**: JSON with workflow runs, failed jobs, failure severity, and fetched timestamp

**Output Structure**:
```json
{
  "repository": "owner/repo",
  "pr_number": 33,
  "summary": {
    "total": 5,
    "critical": 1,
    "major": 3,
    "minor": 1
  },
  "failures": [...],
  "fetched_at": "2025-11-23T17:30:00Z"
}
```

### Advanced Usage

```bash
# Extract only CRITICAL failures
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --json 33 | jq '.failures[] | select(.severity == "critical")'

# Get failure summary for specific workflow
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data --workflow ci-cd 33 | jq '.summary'

# Compare failures across multiple PRs
for pr in 32 33 34; do
  echo "PR $pr:"
  ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data $pr | jq -r '.summary | "\(.total) failures (\(.critical) critical, \(.major) major)"'
done
```

## Arguments

### `fetch-ci-data`

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `PR_NUMBER\|BRANCH` | Pull request number or branch name | Current branch | No |
| `--workflow` | Workflow name filter (e.g., 'ci-cd', 'enhanced-ci') | All workflows | No |
| `--no-cache` | Bypass cache and fetch fresh data | false | No |
| `--help`, `-h` | Show help message | N/A | No |

**Exit Codes**:
- `0` - Success
- `1` - Error (dependency missing, API failure, etc.)
- `2` - No CI failures found

### `ci-quick-review`

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `PR_NUMBER\|BRANCH` | Pull request number or branch name | Current branch | No |
| `--workflow` | Workflow name filter | All workflows | No |
| `--json` | Output JSON only (no formatted display) | false | No |
| `--no-cache` | Bypass cache and fetch fresh data | false | No |
| `--help`, `-h` | Show help message | N/A | No |

**Exit Codes**:
- `0` - Success (CI data fetched, may have failures)
- `1` - Error or merge blocking (Critical/Major failures)
- `2` - No CI failures found (success!)

### `get-ci-job-details`

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `JOB_ID\|JOB_URL` | Job ID (e.g., 56174634733) or full GitHub job URL | N/A | Yes |
| `PR_NUMBER` | Optional PR number for additional context | None | No |
| `--help`, `-h` | Show help message | N/A | No |

**Exit Codes**:
- `0` - Success (job details fetched)
- `1` - Error (dependency missing, API failure, invalid job ID)
- `2` - Job not found

**Note**: Job ID can be extracted from GitHub Actions UI (URL) or from `ci-quick-review` output.

## Output Format

### Markdown Example

```markdown
# CI Failure Analysis - Run #12345678

**Workflow**: CI/CD Pipeline
**Branch**: main
**Trigger**: push
**Status**: ❌ failure
**Duration**: 5m 32s
**Started**: 2025-11-23 14:30:00 UTC
**Completed**: 2025-11-23 14:35:32 UTC

## Severity Breakdown

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 CRITICAL | 2 | Must fix immediately |
| 🟠 MAJOR | 3 | Should fix before merge |
| 🟡 MINOR | 1 | Low priority |

**Total Failures**: 6

---

## 🔴 CRITICAL Failures (2)

### CRITICAL-1: Build Job - Compilation Error
**Job**: Build
**Step**: Compile TypeScript
**Duration**: 1m 45s
**Exit Code**: 2

**Error**:
```
src/services/api.ts:45:12 - error TS2339: Property 'userId' does not exist on type 'Request'.
    return req.userId;
           ~~~
```

**Context** (5 lines before/after):
```typescript
40: async function getUserId(req: Request): Promise<string> {
41:   if (!req.session) {
42:     throw new Error('Session not found');
43:   }
44:
45:   return req.userId;  // ❌ ERROR HERE
46:
47: }
48:
49: export { getUserId };
```

**Root Cause**: TypeScript type mismatch - Request interface missing userId property

**Suggested Fix**:
- Add userId to Request interface via declaration merging
- Or use `(req as any).userId` with proper type guard
- Or extend Request type in types.d.ts

**Similar Failures**: 0 in last 10 runs (NEW failure pattern)

---

### CRITICAL-2: Run Tests - Test Timeout
**Job**: Run Tests
**Step**: Integration Tests
**Duration**: 10m 0s (TIMEOUT)
**Exit Code**: 124

**Error**:
```
Error: Test suite failed to complete within 10 minutes
Timed out waiting for async operation to complete
```

**Context**:
```
Test: "POST /api/users - should create user"
  Status: RUNNING
  Duration: 9m 58s
  Last Activity: Waiting for database connection...
```

**Root Cause**: Database connection pool exhausted or network timeout

**Suggested Fix**:
- Check database connection settings in test environment
- Increase connection pool size
- Verify network connectivity to test database
- Add connection timeout and retry logic

**Similar Failures**: 3 in last 10 runs (⚠️ FLAKY TEST - 30% failure rate)

---

## 🟠 MAJOR Failures (3)

### MAJOR-1: Lint Job - ESLint Violations
**Job**: Lint
**Step**: Run ESLint
**Duration**: 0m 12s
**Exit Code**: 1

**Error**:
```
/home/runner/work/project/src/utils/helpers.js
  23:5  error  'foo' is defined but never used  no-unused-vars
  45:3  error  Unexpected console statement     no-console
```

**Root Cause**: Code quality violations

**Suggested Fix**:
- Remove unused variable 'foo' on line 23
- Replace console.log with proper logging framework on line 45

---

## 🟡 MINOR Failures (1)

### MINOR-1: Deploy Job - Warning Threshold Exceeded
**Job**: Deploy
**Step**: Bundle Size Check
**Duration**: 0m 8s
**Exit Code**: 0 (WARNING)

**Warning**:
```
Bundle size increased by 12% (target: <10%)
  main.js: 245 KB → 275 KB (+30 KB)
```

**Root Cause**: Bundle size regression

**Suggested Fix**:
- Analyze bundle with webpack-bundle-analyzer
- Consider code splitting or lazy loading
- Remove unused dependencies

---

## Summary

### Failure Distribution
- Build errors: 1
- Test failures: 1
- Code quality: 1
- Performance warnings: 1
- Timeouts: 1
- Infrastructure: 1

### Flaky Tests Detected
- ⚠️ "POST /api/users - should create user" (30% failure rate - 3/10 runs)

### Recommendations
1. 🔴 Fix TypeScript compilation error (BLOCKING)
2. 🔴 Investigate database connection timeout (FLAKY)
3. 🟠 Address ESLint violations
4. 🟡 Monitor bundle size growth

### Next Steps
1. Fix CRITICAL failures first (compilation error, test timeout)
2. Run local reproduction of failed tests
3. Check for recent changes to Request interface
4. Review database connection pool configuration
5. Re-run workflow after fixes
```

### JSON Example

```json
{
  "workflow_run": {
    "id": 12345678,
    "name": "CI/CD Pipeline",
    "status": "failure",
    "conclusion": "failure",
    "branch": "main",
    "event": "push",
    "duration_seconds": 332,
    "started_at": "2025-11-23T14:30:00Z",
    "completed_at": "2025-11-23T14:35:32Z"
  },
  "failures": [
    {
      "id": "failure_1",
      "severity": "CRITICAL",
      "job_name": "Build",
      "step_name": "Compile TypeScript",
      "exit_code": 2,
      "duration_seconds": 105,
      "error_message": "error TS2339: Property 'userId' does not exist on type 'Request'",
      "error_type": "compilation_error",
      "file": "src/services/api.ts",
      "line": 45,
      "column": 12,
      "context": {
        "before": ["40: async function getUserId(req: Request): Promise<string> {", "..."],
        "error_line": "45:   return req.userId;",
        "after": ["46:", "47: }"]
      },
      "root_cause": "TypeScript type mismatch - Request interface missing userId property",
      "suggested_fixes": [
        "Add userId to Request interface via declaration merging",
        "Use (req as any).userId with proper type guard",
        "Extend Request type in types.d.ts"
      ],
      "flaky": false,
      "failure_rate": 0.0,
      "last_10_runs": {
        "failures": 0,
        "total": 10
      }
    },
    {
      "id": "failure_2",
      "severity": "CRITICAL",
      "job_name": "Run Tests",
      "step_name": "Integration Tests",
      "exit_code": 124,
      "duration_seconds": 600,
      "error_message": "Test suite failed to complete within 10 minutes",
      "error_type": "timeout",
      "root_cause": "Database connection pool exhausted or network timeout",
      "suggested_fixes": [
        "Check database connection settings",
        "Increase connection pool size",
        "Add connection timeout and retry logic"
      ],
      "flaky": true,
      "failure_rate": 0.3,
      "last_10_runs": {
        "failures": 3,
        "total": 10
      }
    }
  ],
  "summary": {
    "total_failures": 6,
    "critical_count": 2,
    "major_count": 3,
    "minor_count": 1,
    "flaky_tests_count": 1,
    "failure_types": {
      "compilation_error": 1,
      "test_failure": 1,
      "lint_violation": 1,
      "timeout": 1,
      "performance_warning": 1,
      "infrastructure": 1
    }
  },
  "recommendations": [
    {
      "priority": "CRITICAL",
      "action": "Fix TypeScript compilation error",
      "blocking": true
    },
    {
      "priority": "CRITICAL",
      "action": "Investigate database connection timeout",
      "blocking": true,
      "note": "Flaky test detected (30% failure rate)"
    }
  ]
}
```

## Severity Classification Logic

Failures are automatically classified based on error patterns:

### 🔴 CRITICAL (Must Fix Immediately)
**Blocking failures** that prevent build/deploy:
- Compilation errors
- Build failures
- Critical test failures (not flaky)
- Deployment failures
- Security vulnerabilities
- Infrastructure failures

**Exit Code**: Always causes CI to fail

### 🟠 MAJOR (Should Fix Before Merge)
**Important failures** that affect quality:
- Test failures (unit/integration)
- Linting errors with high severity
- Performance regressions
- Missing required checks
- Code quality violations

**Exit Code**: Should cause CI to fail in strict mode

### 🟡 MINOR (Low Priority)
**Quality issues** that can be deferred:
- Warnings (bundle size, deprecations)
- Optional check failures
- Documentation issues
- Low-priority linting warnings
- Performance warnings (non-blocking)

**Exit Code**: Should not cause CI to fail

### Flaky Test Detection

Tests are marked as flaky when:
- Failure rate > 10% in last 10 runs
- Same test fails intermittently
- Timeout-based failures with inconsistent timing

**Flaky tests get special treatment**:
- Marked with ⚠️ warning symbol
- Failure rate displayed
- Suggested to investigate root cause
- May be retried automatically

## Error Pattern Detection

### Build Errors
- **Pattern**: Exit code 2, compilation errors, dependency resolution
- **Keywords**: `error`, `failed to compile`, `cannot resolve`, `ENOENT`
- **Classification**: CRITICAL

### Test Failures
- **Pattern**: Exit code 1, test assertion failures, timeout
- **Keywords**: `FAILED`, `AssertionError`, `timeout`, `expected`
- **Classification**: CRITICAL (if not flaky), MAJOR (if flaky)

### Linting Issues
- **Pattern**: Exit code 1, code quality violations
- **Keywords**: `eslint`, `warning`, `violation`, `no-unused-vars`
- **Classification**: MAJOR

### Timeouts
- **Pattern**: Exit code 124, duration at timeout threshold
- **Keywords**: `timeout`, `timed out`, `exceeded`
- **Classification**: CRITICAL (first occurrence), MAJOR (if flaky)

### Infrastructure Issues
- **Pattern**: Exit code 137, 143, resource limits
- **Keywords**: `OOMKilled`, `no space left`, `connection refused`
- **Classification**: CRITICAL

## Benefits

### For Developers
- ✅ Quick root cause identification
- ✅ Actionable fix suggestions
- ✅ Context-aware error messages
- ✅ Flaky test detection
- ✅ Historical failure tracking

### For Teams
- ✅ Standardized failure classification
- ✅ Consistent debugging workflow
- ✅ Reduced mean time to resolution (MTTR)
- ✅ Flaky test visibility
- ✅ CI health monitoring

### For CI/CD
- ✅ Automated failure analysis
- ✅ Integration with GitHub Actions
- ✅ JSON output for programmatic processing
- ✅ Strict mode for blocking failures
- ✅ Historical failure tracking

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: CI/CD Pipeline

on:
  pull_request:
  push:
    branches: [main]

jobs:
  analyze-failures:
    if: failure()
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Analyze CI Failures
        run: |
          # Quick review of CI failures
          ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review ${{ github.event.pull_request.number }}

          # Or post JSON summary to PR
          if [ "${{ github.event_name }}" == "pull_request" ]; then
            SUMMARY=$(${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review ${{ github.event.pull_request.number }})
            gh pr comment ${{ github.event.pull_request.number }} \
              --body "$SUMMARY"
          fi

      - name: Upload Failure Analysis
        uses: actions/upload-artifact@v4
        with:
          name: ci-failure-analysis
          path: ./tmp/ci-failures.json
```

### Pre-Commit Hook Example

```bash
#!/bin/bash
# .git/hooks/pre-push

# Check CI status for current branch before pushing
if ! ${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review; then
  echo ""
  echo "⚠️  Warning: CI failures detected on current branch"
  echo "Review failures above before pushing."
  echo ""
  read -p "Continue with push? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
fi
```

## Performance Notes

### Caching Strategy

The skill implements intelligent caching to reduce GitHub API calls:

**Cache TTL**: 5 minutes for workflow run data
**Cache Location**: `{REPO}/tmp/.ci-failures-cache/`
**Cache Key**: `run-id-{RUN_ID}-{timestamp}`

**Cache Invalidation**:
- Automatic after 5 minutes
- Manual via `--no-cache` flag
- On new commits to branch

**Benefits**:
- ✅ Faster subsequent analyses (< 100ms vs 2-5s)
- ✅ Reduced GitHub API rate limit usage
- ✅ Offline analysis capability

### API Rate Limits

GitHub API rate limits:
- **Authenticated**: 5,000 requests/hour
- **Unauthenticated**: 60 requests/hour

**Optimization**:
- Workflow runs: 1 request per run
- Job logs: 1 request per job (only if `--include-logs`)
- Caching reduces repeat requests by ~80%

**Estimated Usage**:
- Single run analysis: 3-5 requests (with logs)
- Single run analysis: 1-2 requests (without logs)
- Cached analysis: 0 requests

## Implementation Details

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  CI FAILURES SKILL ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [GitHub Actions API]                                        │
│         ↓                                                   │
│  [fetch-ci-failures] ← gh CLI wrapper                       │
│         ↓                                                   │
│  [Cache Layer] (5-min TTL)                                  │
│         ↓                                                   │
│  [analyze-ci-failures] ← Pattern detection + classification  │
│         ↓                                                   │
│  [Output Formatter] ← Markdown or JSON                      │
│         ↓                                                   │
│  [Report] → ./tmp/ci-debug-*.md                            │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Fetch Phase**:
   - Query GitHub Actions API via `gh` CLI
   - Retrieve workflow runs, jobs, and steps
   - Cache raw data for 5 minutes
   - Extract logs for failed steps (optional)

2. **Analysis Phase**:
   - Parse error messages and stack traces
   - Classify severity based on patterns
   - Extract file:line references
   - Detect flaky tests via historical data
   - Generate root cause suggestions

3. **Output Phase**:
   - Format as Markdown or JSON
   - Include context (logs, code snippets)
   - Add fix suggestions
   - Save to `./tmp/` directory

### Error Handling

**GitHub API Errors**:
- Rate limit exceeded → Display cache-only results with warning
- Authentication failure → Prompt for `gh auth login`
- Network timeout → Retry up to 3 times with exponential backoff
- 404 Not Found → Check workflow run ID validity

**Analysis Errors**:
- Malformed JSON → Skip entry and log warning
- Missing required fields → Use defaults and continue
- Pattern match failures → Default to MINOR severity

**Exit Codes**:
- `0` - Success (no failures or analysis complete)
- `1` - Failures found (strict mode)
- `2` - Invalid arguments
- `3` - GitHub API error
- `4` - Cache error (non-fatal, continues)

## Dependencies

Required tools:

**GitHub CLI** (`gh`):
```bash
brew install gh
gh auth login
```

**jq** (JSON processor):
```bash
brew install jq
```

**Optional**:
- `curl` - Alternative to gh for API access
- `git` - For branch detection

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/`

**Executables**:
- `${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review` - One-command quick review with concise summary (RECOMMENDED - Tier 1)
- `${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details` - Deep-dive investigation into specific job failures (Tier 2)
- `${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data` - Fetch CI failure data with severity classification (Advanced)

## Architecture Notes

### Why Direct GitHub API?

CI failures analysis uses direct GitHub API calls (via `gh` CLI) rather than event-based architecture because:
- **External Service**: GitHub Actions is a third-party service outside OmniNode infrastructure
- **Real-Time Data**: Workflow run data must be fetched in real-time from GitHub
- **Simplicity**: Direct API calls are simpler for external read-only operations
- **No State**: Failure analysis is stateless - no persistence or coordination needed

### When to Use Events vs Direct API

**Use Event-Based Architecture** for:
- ✅ Internal OmniNode services (intelligence, routing, observability)
- ✅ Services requiring persistence or state management
- ✅ Multi-service coordination and orchestration
- ✅ Async operations with retries and DLQ

**Use Direct API/MCP** for:
- ✅ External third-party services (GitHub, Linear, etc.)
- ✅ Real-time read-only operations
- ✅ Simple request-response patterns without state
- ✅ CI/CD integration where events are not available

## Future Enhancements

**Planned Features**:
- [ ] Multi-repository analysis (compare CI health across repos)
- [ ] Slack/Discord notifications for CRITICAL failures
- [ ] Integration with Linear for automatic ticket creation
- [ ] ML-based root cause prediction
- [ ] Flaky test auto-retry with smart backoff
- [ ] Performance regression detection
- [ ] Cost analysis (CI minutes usage tracking)
- [ ] Custom severity classification rules (YAML config)

**Integration Roadmap**:
- [ ] Event-based notifications via Kafka (when failure detected)
- [ ] PostgreSQL storage for historical failure tracking
- [ ] Grafana dashboard for CI health metrics
- [ ] OpenTelemetry tracing for CI pipeline observability

## Related Skills

**Debugging & Analysis**:
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/` - PR review and feedback analysis
- `${CLAUDE_PLUGIN_ROOT}/skills/system-status/` - System health monitoring
- `${CLAUDE_PLUGIN_ROOT}/skills/agent-tracking/` - Agent execution tracking

**CI/CD Integration**:
- GitHub Actions workflows in `.github/workflows/`
- Event alignment plan: `/docs/events/EVENT_ALIGNMENT_PLAN.md`

**Linear Integration** (for ticket creation from failures):
- `${CLAUDE_PLUGIN_ROOT}/skills/linear/create-ticket` - Create Linear tickets
- MCP Linear server: `mcp__linear-server__create_issue`

## Examples

### Example 1: Quick Review of Latest CI Failure

```bash
# Quick review of current branch
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review

# Terminal displays colorized summary with actionable suggestions
```

### Example 2: Review Specific PR

```bash
# Review CI failures for PR #33
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33

# View CRITICAL failures only (JSON output)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --json 33 | \
  jq '.failures[] | select(.severity == "critical")'
```

### Example 3: Filter to Specific Workflow

```bash
# Check only CI/CD workflow failures
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --workflow ci-cd 33

# Check enhanced-ci workflow
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review --workflow enhanced-ci 33
```

### Example 4: Programmatic Analysis

```bash
# Fetch raw data for custom processing
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/fetch-ci-data 33 > ./tmp/ci-data.json

# Extract failure summary
jq '.summary' ./tmp/ci-data.json

# List all failed job names
jq -r '.failures[] | "\(.workflow): \(.job)"' ./tmp/ci-data.json | sort -u
```

### Example 5: Two-Tier Investigation Workflow

```bash
# Step 1: Get overview of all failures (Tier 1)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/ci-quick-review 33

# Output shows:
# CI FAILURES SUMMARY
# ...
# Failed Jobs:
#   CI/CD Pipeline:
#     ● Build → Compile TypeScript (Job ID: 56174634733)
#     ● Run Tests → Integration Tests (Job ID: 56174634821)
# ...

# Step 2: Deep-dive into specific failures (Tier 2)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details 56174634733

# See complete logs, stack traces, and contextual suggestions

# Step 3: Investigate second failure
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details 56174634821

# Compare patterns across multiple failed jobs
```

### Example 6: Using Job URLs

```bash
# Copy job URL from GitHub Actions UI
# URL: https://github.com/owner/repo/actions/runs/12345678/job/56174634733

# Investigate using full URL (job ID automatically extracted)
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details \
  https://github.com/owner/repo/actions/runs/12345678/job/56174634733

# Or just use the job ID
${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/get-ci-job-details 56174634733
```

## See Also

- GitHub Actions API: https://docs.github.com/en/rest/actions
- GitHub CLI Manual: https://cli.github.com/manual/
- PR Review Skills: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md`
- System Status Skills: `${CLAUDE_PLUGIN_ROOT}/skills/system-status/SKILL.md`
- Event Alignment Plan: `/docs/events/EVENT_ALIGNMENT_PLAN.md`
