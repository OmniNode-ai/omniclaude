---
name: pr-review-comprehensive
description: Comprehensive PR review with strict priority-based organization and merge readiness assessment
level: basic
debug: false
---

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT read
files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run pr-review for PR #<pr_number>",
  prompt="Run the pr-review skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only — do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Comprehensive PR Review

Production-ready PR review system that fetches all feedback from GitHub, organizes by priority, and enforces strict merge requirements.

## Seam Contract Check (Pre-Review Gate)

Run this gate **before all other review steps** for every PR.

### 1. Extract ticket_id from PR

```
Branch pattern: omn-(\d+) (case-insensitive) → OMN-{N}
PR title pattern: \[OMN-(\d+)\] or OMN-(\d+):
```

If no ticket_id found: skip contract check, log "no ticket ID in PR" and proceed to Step 1.

### 2. Locate contract

```
Primary:  $ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml   (if ONEX_CC_REPO_PATH is set)
Fallback: $OMNI_HOME/onex_change_control/contracts/{ticket_id}.yaml
```

**If contract not found:**
- PR touches Kafka topic strings or event schemas → add MAJOR finding: "Seam signals detected but no contract found — run /generate-ticket-contract"
- No seam signals → skip silently (not an error)

### 3. If contract found AND is_seam_ticket=true

Invoke the `contract-compliance-check` skill:

```
/contract-compliance-check {ticket_id}
```

Route result as follows:

| Result | Action |
|--------|--------|
| `BLOCK` | Add as CRITICAL finding; halt review (do not proceed to Step 1) |
| `WARN` | Add as MAJOR finding; continue review (proceed to Step 1) |
| `PASS` | Log pass; continue review (proceed to Step 1) |

**emergency_bypass semantics**: If `emergency_bypass.enabled=true` with non-empty `justification` and `follow_up_ticket_id`, downgrade BLOCK to WARN and continue.

### 4. Report

Post contract check result as a PR comment via `gh pr comment`:

```bash
gh pr comment {PR_NUMBER} --body "$(cat <<'EOF'
## Seam Contract Check — {ticket_id}

{contract_compliance_check_output}
EOF
)"
```

---

## 🚨 CRITICAL: ALWAYS DISPATCH TO POLYMORPHIC AGENT

**DO NOT run bash scripts directly.** When this skill is invoked, you MUST dispatch to a polymorphic-agent.

### ❌ WRONG - Running bash directly:
```
Bash(${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues 30)
Bash(${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-quick-review 22)
```

### ✅ CORRECT - Dispatch to polymorphic-agent:
```
Task(
  subagent_type="onex:polymorphic-agent",
  description="PR review for #30",
  prompt="Review PR #30. Use the pr-review skill tools:
    1. Run: ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues 30
    2. Analyze the output and categorize issues
    3. Report findings organized by priority (CRITICAL/MAJOR/MINOR/NIT)

    Available tools in ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/:
    - collate-issues <PR#> - Get all issues from PR
    - collate-issues-with-ci <PR#> - Get PR issues + CI failures
    - pr-quick-review <PR#> - Quick summary review
    - fetch-pr-data <PR#> - Raw PR data from GitHub

    Return a summary with:
    - Count by priority level
    - Merge readiness assessment
    - List of issues to fix"
)
```

**WHY**: Polymorphic agents have full ONEX capabilities, intelligence integration, quality gates, and proper observability. Running bash directly bypasses all of this.

## Skills Available

1. **pr-quick-review** - One-command quick review (NEW - RECOMMENDED)
2. **fetch-pr-data** - Fetch all PR data from 4 GitHub endpoints
3. **analyze-pr-comments** - Pre-process raw PR data into categorized analysis (NEW)
4. **review-pr** - Comprehensive review with priority organization
5. **pr-review-production** - Production-grade review wrapper with strict standards

## Priority System

### 🔴 CRITICAL (Must Address)
**Blocking issues** that MUST be resolved before merge:
- Security vulnerabilities
- Data loss risks
- System crashes or breaking changes
- Critical bugs that affect core functionality

**Merge Status**: ❌ Cannot merge until resolved

### 🟠 MAJOR (Should Address)
**Important issues** that SHOULD be resolved before merge:
- Performance problems
- Incorrect behavior
- Missing or failing tests
- Significant code quality issues
- Breaking API changes

**Merge Status**: ⚠️  Should resolve before merge

### 🟡 MINOR (Should Address)
**Quality issues** that should be addressed:
- Code quality improvements
- Missing documentation
- Edge case handling
- Non-critical refactoring
- Minor performance optimizations

**Merge Status**: ⚠️  Should resolve (not blocking)

### ⚪ NIT / Nice to Have (Optional)
**Optional improvements** that can be deferred:
- Formatting preferences
- Variable naming suggestions
- Minor refactoring ideas
- Stylistic improvements
- Non-blocking suggestions

**Merge Status**: ✅ Can merge even if nits remain

## Merge Requirements

**✅ Can Merge When:**
- ALL Critical issues resolved
- ALL Major issues resolved
- ALL Minor issues resolved
- Nits are OPTIONAL (nice to have)

**❌ Cannot Merge When:**
- ANY Critical issues remain
- ANY Major issues remain
- ANY Minor issues remain

## Usage

> **📁 Temporary Files**: Always use repository-local `./tmp/` directory for temporary files.
> Never use system `/tmp/` - this violates the repository pattern established in PR #36.
> All examples below correctly use `{REPO}/tmp/` for output files.

### Quick Review (RECOMMENDED)

**Single command for most use cases** - fetches, categorizes, and displays automatically:

```bash
# Quick review with smart defaults (saves to {REPO}/tmp/pr-review-22.md)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-quick-review 22

# Save to specific file
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-quick-review 22 --save ./my-review.md

# JSON output for scripting
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-quick-review 22 --json > pr22.json

# CI/CD mode (fails if issues found)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-quick-review 22 --strict
```

**Benefits**:
- ✅ Single command (no need to chain fetch + review)
- ✅ Smart defaults (auto-saves to tmp/)
- ✅ Auto-displays output in terminal
- ✅ Fewer agent actions needed

### Pre-Categorized Analysis (For Agents)

**New in v2**: Pre-process PR data into structured JSON for agent consumption without manual jq parsing.

```bash
# Analyze PR data from fetch-pr-data
fetch-pr-data 36 | analyze-pr-comments > categorized.json

# From file
analyze-pr-comments pr_data.json > analysis.json

# Pipeline usage
fetch-pr-data 36 | analyze-pr-comments | jq '.summary'
```

**Output Structure**:
```json
{
  "pr_number": 36,
  "analysis_timestamp": "2025-11-17T14:30:00Z",
  "last_commit": {
    "sha": "b4fe0d78...",
    "timestamp": "2025-11-17T12:00:00Z"
  },
  "categorized_issues": {
    "critical": [{
      "id": "issue_1",
      "source": "issue_comment",
      "author": "claude-code[bot]",
      "severity": "CRITICAL",
      "title": "Run Tests job hung",
      "description": "...",
      "file": "ci.yml",
      "line": 45,
      "status": "unaddressed",
      "created_at": "2025-11-17T13:00:00Z",
      "structured_sections": {...}
    }],
    "major": [...],
    "minor": [...],
    "nitpicks": [...]
  },
  "summary": {
    "total_critical": 4,
    "total_major": 16,
    "total_minor": 7,
    "total_nitpicks": 19,
    "total_all": 46,
    "total_actionable": 27,
    "unaddressed_critical": 4,
    "unaddressed_major": 14,
    "unaddressed_minor": 3
  },
  "structured_bot_reviews": [...]
}
```

**Features**:
- ✅ Pre-categorized by severity (CRITICAL/MAJOR/MINOR/NITPICK)
- ✅ File:line references extracted from comments
- ✅ Status tracking (unaddressed vs potentially_addressed)
- ✅ Structured bot review sections parsed
- ✅ Unique IDs for tracking
- ✅ No manual jq parsing needed by agents

**Why This Matters for Agents**:
- Eliminates complex bash loops and jq parsing
- Provides ready-to-use structured data
- Includes status information for prioritization
- Reduces agent token usage and processing time

### Basic Review (Advanced)

```bash
# Review PR with priority organization
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/review-pr 22

# Output:
# - Priority breakdown (Critical/Major/Minor/Nit)
# - Merge readiness assessment
# - Organized issues by priority
# - Saved to {REPO}/tmp/pr-review-22.md
```

### Strict Mode (CI/CD)

```bash
# Fail if any Critical/Major/Minor issues found
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/review-pr 22 --strict

# Exit codes:
#   0 - Ready to merge (only nits or no issues)
#   2 - Not ready (Critical/Major/Minor issues found)
```

### Custom Output

```bash
# Save to specific file
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/review-pr 22 --output-file ./tmp/pr22-review.md

# JSON output for programmatic processing
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/review-pr 22 --json > pr22.json
```

### Production Review (NEW)

**Production-grade review with stricter standards and Linear integration:**

```bash
# Production review (all Critical/Major/Minor MUST be resolved)
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-review-production 22

# Create Linear tickets for Critical and Major issues
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-review-production 22 \
  --create-linear-tickets \
  --team 9bdff6a3-f4ef-4ff7-b29a-6c4cf44371e6

# JSON output for CI/CD pipelines
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-review-production 22 --json

# Exit codes:
#   0 - Ready for production (all Critical/Major/Minor resolved)
#   1 - Invalid arguments
#   2 - Not ready (unresolved Critical/Major/Minor issues)
#   3 - GitHub API error
```

**Production Requirements:**
- ✅ ALL Critical issues MUST be resolved (BLOCKING)
- ✅ ALL Major issues MUST be resolved (BLOCKING)
- ✅ ALL Minor issues MUST be resolved (BLOCKING)
- ⚪ Nits are optional (nice to have, NOT blocking)

## Integration with CI/CD

### GitHub Actions Example

```yaml
- name: PR Review
  run: |
    ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/review-pr ${{ github.event.pull_request.number }} --strict

    # Upload review artifact
    if [ -f ./tmp/pr-review-*.md ]; then
      gh pr comment ${{ github.event.pull_request.number }} \
        --body-file ./tmp/pr-review-*.md
    fi
```

## Output Format

### Markdown Example

```markdown
# PR #22 - Review Summary

**Generated**: 2025-11-13 10:30:00

## Priority Breakdown

| Priority | Count | Status |
|----------|-------|--------|
| 🔴 CRITICAL | 2 | Must resolve before merge |
| 🟠 MAJOR | 5 | Should resolve before merge |
| 🟡 MINOR | 8 | Should resolve |
| ⚪ NIT | 12 | Optional (nice to have) |

**Total Issues**: 27

## Merge Readiness

❌ **NOT READY TO MERGE**

- ❌ 2 Critical issue(s) must be resolved
- ❌ 5 Major issue(s) should be resolved
- ⚠️  8 Minor issue(s) should be resolved

---

## 🔴 CRITICAL Issues (2)

### CRITICAL-1: coderabbitai[bot]
**File**: `agents/lib/security.py`

SQL injection vulnerability in user input handling...

---

### CRITICAL-2: claude[bot]
**File**: `services/api.py`

Unauthenticated endpoint exposes sensitive data...

---

## 🟠 MAJOR Issues (5)

...
```

### JSON Example

```json
{
  "critical": [
    {
      "author": "coderabbitai[bot]",
      "path": "agents/lib/security.py",
      "body": "SQL injection vulnerability...",
      "id": 123456
    }
  ],
  "major": [...],
  "minor": [...],
  "nit": [...],
  "summary": {
    "critical_count": 2,
    "major_count": 5,
    "minor_count": 8,
    "nit_count": 12,
    "total": 27
  }
}
```

## Priority Classification Logic

Issues are automatically classified based on keywords:

**CRITICAL Keywords**:
- `critical`, `security`, `vulnerability`, `data loss`, `crash`, `breaking change`

**MAJOR Keywords**:
- `major`, `bug`, `error`, `incorrect`, `performance`, `test`, `missing`, `should`, `important`

**NIT Keywords**:
- `nit`, `nitpick`, `minor`, `consider`, `suggestion`, `optional`, `nice to have`, `style`, `formatting`

**Default**: If no keywords match → classified as MINOR

## Benefits

### For Developers
- ✅ Clear priority guidance on what must be fixed
- ✅ Focus on blocking issues first
- ✅ Optional nits don't block progress
- ✅ Automated merge readiness assessment

### For Reviewers
- ✅ Standardized priority system
- ✅ All feedback organized in one place
- ✅ No missed comments (4 GitHub endpoints)
- ✅ Clear merge criteria

### For Teams
- ✅ Consistent review standards
- ✅ Reduced review friction (nits are optional)
- ✅ CI/CD integration support
- ✅ Audit trail of all feedback

## Comparison: Review Modes

### Standard Review (`review-pr`)
**Best for**: Development, feature branches, regular PRs

- ✅ All comments fetched and organized
- ✅ Automatic priority classification
- ✅ Clear merge requirements (Critical/Major/Minor)
- ✅ Nits marked as optional
- ✅ Ready-to-share markdown report
- ⚪ Flexible standards for development velocity

### Production Review (`pr-review-production`)
**Best for**: Production deployments, release branches, critical PRs

- ✅ Same features as standard review
- ✅ **Strict production-grade standards**
- ✅ **All Critical/Major/Minor MUST be resolved**
- ✅ **Optional Linear ticket creation** for tracking
- ✅ **Production readiness certification**
- 🔴 Zero tolerance for unresolved issues (except nits)

### When to Use Which

| Scenario | Use | Reason |
|----------|-----|--------|
| Feature branch → dev | `review-pr` | Development velocity matters |
| Dev → staging | `review-pr --strict` | Catch issues before production |
| Staging → production | `pr-review-production` | Zero tolerance, full tracking |
| Hotfix → production | `pr-review-production` | Critical path, must be perfect |
| Experimental PR | `review-pr` | Allow flexibility for exploration |

## Skills Location

**Claude Code Access**: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/`
**Executables**:
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-quick-review` - One-command quick review (RECOMMENDED)
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/fetch-pr-data` - Fetch all PR data from 4 GitHub endpoints
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/analyze-pr-comments` - Pre-process raw data into categorized analysis (NEW)
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/review-pr` - Comprehensive review with priority organization
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-review-production` - Production-grade wrapper (NEW)

## Dependencies

Required tools (install with `brew install gh jq`):
- `gh` - GitHub CLI
- `jq` - JSON processor

## Tier Routing (OMN-2828)

PR data fetching uses tier-aware backend selection:

| Tier | Backend | Details |
|------|---------|---------|
| `FULL_ONEX` | `node_git_effect.pr_view()` | Typed Pydantic models, structured PR data |
| `STANDALONE` | `_bin/pr-merge-readiness.sh` | Shell script wrapping `gh pr view` with merge readiness assessment |
| `EVENT_BUS` | `_bin/pr-merge-readiness.sh` | Same as STANDALONE |

Tier detection: see `@_lib/tier-routing/helpers.md`.

### FULL_ONEX Path

```python
from omniclaude.nodes.node_git_effect.models import (
    GitOperation, ModelGitRequest,
)

request = ModelGitRequest(
    operation=GitOperation.PR_VIEW,
    repo=repo,
    pr_number=pr_number,
    json_fields=[
        "number", "title", "mergeable", "mergeStateStatus",
        "reviewDecision", "statusCheckRollup", "headRefName",
        "baseRefName", "isDraft", "reviewRequests", "latestReviews",
    ],
)
result = await handler.pr_view(request)
```

### STANDALONE Path

```bash
${CLAUDE_PLUGIN_ROOT}/_bin/pr-merge-readiness.sh --pr {N} --repo {repo}
# Returns: { ready, mergeable, ci_status, review_decision, merge_state_status, blockers }
```

The `_bin/pr-merge-readiness.sh` script provides a unified merge readiness assessment
including CI status, review decision, and blocker list -- reducing the number of separate
`gh` calls skills need to make.

### Note on Review Comment Fetching

The review **comment** fetching (collate-issues, fetch-pr-data, analyze-pr-comments) is
always direct `gh` CLI -- these are read-only operations fetching PR feedback from GitHub's
4 endpoints. The tier routing above applies only to merge readiness state assessment, not
comment collection.

## Architecture Notes

### Why Not Event-Based?

PR review uses direct GitHub API calls (via `gh` CLI) rather than event-based architecture because:
- **External Service**: GitHub is a third-party service outside OmniNode infrastructure
- **Real-Time Data**: PR feedback must be fetched in real-time from GitHub's 4 endpoints
- **Simplicity**: Direct API calls are simpler for external read-only operations
- **No State**: Review analysis is stateless -- no persistence or coordination needed

### When to Use Events

Use event-based architecture for:
- Internal OmniNode services (intelligence, routing, observability)
- Services requiring persistence or state management
- Multi-service coordination and orchestration
- Async operations with retries and DLQ

Use direct API/MCP for:
- External third-party services (GitHub, Linear, etc.)
- Real-time read-only operations
- Simple request-response patterns without state

## Pydantic-Backed System (v2)

The PR review skill now has a type-safe Python backend using Pydantic models.

### Files
- `models.py` - Pydantic v2 models for all PR data structures
- `fetcher.py` - Type-safe GitHub API fetcher
- `analyzer.py` - Comment analyzer with Claude bot detection
- `pr_review.py` - Unified entry point

### Usage (New)
```bash
# Quick summary
./pr_review.py 38

# Full analysis
./pr_review.py 38 --full

# Only Claude bot comments (NEVER MISSED!)
./pr_review.py 38 --claude-only

# Merge blockers only
./pr_review.py 38 --blockers

# JSON output
./pr_review.py 38 --json

# Markdown report
./pr_review.py 38 --markdown --save
```

### Key Features
- **Type Safety**: All data validated through Pydantic models
- **Claude Bot Detection**: 7 patterns checked, NEVER misses Claude comments
- **Structured Sections**: Parses "Must Fix", "Should Fix" sections
- **Caching**: 5-minute TTL cache at `/tmp/pr-review-cache-v2/`
- **Multiple Output Formats**: Summary, JSON, Markdown
- **Exit Codes**: 0 = ready to merge, 1 = has blockers

### Backward Compatibility

Use the wrapper script for backward compatibility with existing workflows:

```bash
# Same as pr_review.py but via bash wrapper
${CLAUDE_PLUGIN_ROOT}/skills/pr-review/pr-review-v2 38 --full
```

### Python API

```python
from models import PRData, PRAnalysis, CommentSeverity, BotType
from fetcher import PRFetcher
from analyzer import PRAnalyzer, generate_markdown_report

# Fetch PR data
fetcher = PRFetcher("owner/repo", 38)
pr_data = fetcher.fetch()

# Analyze
analyzer = PRAnalyzer(pr_data)
analysis = analyzer.analyze()

# Check merge readiness
if analysis.merge_blockers:
    print(f"Blocked by {len(analysis.merge_blockers)} issues")

# Get Claude bot comments (NEVER missed)
for comment in analysis.claude_issues:
    print(f"[{comment.severity.value}] {comment.body[:100]}")

# Generate markdown report
report = generate_markdown_report(analysis)
```

## See Also

- GitHub API Docs: https://docs.github.com/en/rest/pulls
- Linear skills: `${CLAUDE_PLUGIN_ROOT}/skills/linear/`
- `_bin/pr-merge-readiness.sh` -- STANDALONE merge readiness assessment backend
- `_lib/tier-routing/helpers.md` -- tier detection and routing helpers
