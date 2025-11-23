# PR Release Ready - Comprehensive Pre-Merge Review

**Purpose**: Verify PR is production-ready with all feedback addressed, including polish items.

**Philosophy**: Nothing ships with known issues. All feedback should be addressed or explicitly documented as acceptable.

---

## Execution

```bash
# PR number is provided as $1
PR_NUM="${1:-}"

if [[ -z "$PR_NUM" ]]; then
    echo "Usage: /pr-release-ready <PR#>"
    exit 1
fi

# Use optimized collate-issues script with nitpicks included
~/.claude/skills/pr-review/collate-issues "$PR_NUM" --include-nitpicks
```

---

## What This Provides

**Comprehensive review including ALL feedback categories**:
- ✅ **Critical issues** (must fix before merge)
- ✅ **Major issues** (should fix to prevent tech debt)
- ✅ **Minor issues** (fix now to maintain quality)
- ✅ **Nitpicks** (polish for production release)

**Performance**:
- < 3 seconds (with caching)
- ~800 tokens (vs 10K+ before)
- 1 tool call (vs 15+ before)

**Data Sources**:
- Fetches from all 4 GitHub endpoints (reviews, inline comments, PR comments, issue comments)
- Intelligently categorizes using Claude bot structured recommendations
- Prioritizes issue_comments[] first (where Claude Code bot posts comprehensive reviews)

---

## Difference from /pr-dev-review

| Command | Nitpicks Included? | Use Case |
|---------|-------------------|----------|
| `/pr-dev-review` | ❌ No | Development focus - actionable issues only |
| `/pr-release-ready` | ✅ Yes | Production release - comprehensive polish |

**When to use this command**:
- Before final merge to main/master
- Production release preparation
- When you want comprehensive code review including polish items
- When nothing should ship with known issues

**When to use /pr-dev-review instead**:
- During active development
- When you want to focus on critical/major/minor only
- When nitpicks are deferred to later polish pass
