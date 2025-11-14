---
name: pr-review-comprehensive
description: Comprehensive PR review with strict priority-based organization and merge readiness assessment
---

# Comprehensive PR Review

Production-ready PR review system that fetches all feedback from GitHub, organizes by priority, and enforces strict merge requirements.

## Skills Available

1. **pr-quick-review** - One-command quick review (NEW - RECOMMENDED)
2. **fetch-pr-data** - Fetch all PR data from 4 GitHub endpoints
3. **review-pr** - Comprehensive review with priority organization
4. **pr-review-production** - Production-grade review wrapper with strict standards

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

### Quick Review (RECOMMENDED)

**Single command for most use cases** - fetches, categorizes, and displays automatically:

```bash
# Quick review with smart defaults (saves to {REPO}/tmp/pr-review-22.md)
~/.claude/skills/pr-review/pr-quick-review 22

# Save to specific file
~/.claude/skills/pr-review/pr-quick-review 22 --save ./my-review.md

# JSON output for scripting
~/.claude/skills/pr-review/pr-quick-review 22 --json > pr22.json

# CI/CD mode (fails if issues found)
~/.claude/skills/pr-review/pr-quick-review 22 --strict
```

**Benefits**:
- ✅ Single command (no need to chain fetch + review)
- ✅ Smart defaults (auto-saves to tmp/)
- ✅ Auto-displays output in terminal
- ✅ Fewer agent actions needed

### Basic Review (Advanced)

```bash
# Review PR with priority organization
~/.claude/skills/pr-review/review-pr 22

# Output:
# - Priority breakdown (Critical/Major/Minor/Nit)
# - Merge readiness assessment
# - Organized issues by priority
# - Saved to {REPO}/tmp/pr-review-22.md
```

### Strict Mode (CI/CD)

```bash
# Fail if any Critical/Major/Minor issues found
~/.claude/skills/pr-review/review-pr 22 --strict

# Exit codes:
#   0 - Ready to merge (only nits or no issues)
#   2 - Not ready (Critical/Major/Minor issues found)
```

### Custom Output

```bash
# Save to specific file
~/.claude/skills/pr-review/review-pr 22 --output-file ./tmp/pr22-review.md

# JSON output for programmatic processing
~/.claude/skills/pr-review/review-pr 22 --json > pr22.json
```

### Production Review (NEW)

**Production-grade review with stricter standards and Linear integration:**

```bash
# Production review (all Critical/Major/Minor MUST be resolved)
~/.claude/skills/pr-review/pr-review-production 22

# Create Linear tickets for Critical and Major issues
~/.claude/skills/pr-review/pr-review-production 22 \
  --create-linear-tickets \
  --team 9bdff6a3-f4ef-4ff7-b29a-6c4cf44371e6

# JSON output for CI/CD pipelines
~/.claude/skills/pr-review/pr-review-production 22 --json

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
    ~/.claude/skills/pr-review/review-pr ${{ github.event.pull_request.number }} --strict

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

**Claude Code Access**: `~/.claude/skills/pr-review/`
**Executables**:
- `~/.claude/skills/pr-review/pr-quick-review` - One-command quick review (RECOMMENDED)
- `~/.claude/skills/pr-review/fetch-pr-data` - Fetch all PR data
- `~/.claude/skills/pr-review/review-pr` - Comprehensive review with priority organization
- `~/.claude/skills/pr-review/pr-review-production` - Production-grade wrapper (NEW)

## Dependencies

Required tools (install with `brew install gh jq`):
- `gh` - GitHub CLI
- `jq` - JSON processor

## Architecture Notes

### Why Not Event-Based?

PR review uses direct GitHub API calls (via `gh` CLI) rather than event-based architecture because:
- **External Service**: GitHub is a third-party service outside OmniNode infrastructure
- **Real-Time Data**: PR feedback must be fetched in real-time from GitHub's 4 endpoints
- **Simplicity**: Direct API calls are simpler for external read-only operations
- **No State**: Review analysis is stateless - no persistence or coordination needed

### When to Use Events

Use event-based architecture for:
- ✅ Internal OmniNode services (intelligence, routing, observability)
- ✅ Services requiring persistence or state management
- ✅ Multi-service coordination and orchestration
- ✅ Async operations with retries and DLQ

Use direct API/MCP for:
- ✅ External third-party services (GitHub, Linear, etc.)
- ✅ Real-time read-only operations
- ✅ Simple request-response patterns without state

## See Also

- GitHub API Docs: https://docs.github.com/en/rest/pulls
- Linear skills: `~/.claude/skills/linear/`
- Event alignment plan: `/docs/events/EVENT_ALIGNMENT_PLAN.md`
