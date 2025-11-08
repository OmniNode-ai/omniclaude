# PR Dev Review - Development-Focused Review

**Purpose**: Identify issues that should be fixed during development to prevent tech debt.

**Philosophy**: Fix anything that affects code quality, correctness, or maintainability. Only defer pure cosmetic polish.

---

## Execution

Use the Task tool to dispatch to the polymorphic agent for PR analysis:

```
description: "PR development review and categorization"
subagent_type: "polymorphic-agent"
prompt: "Execute a development-focused PR review with the following requirements:

## PR Analysis Task

Analyze the provided PR and categorize all comments/reviews into actionable categories.

**User will provide**: PR number (e.g., "18") or full GitHub PR URL

### 🔴 CRITICAL (MUST FIX - blocks merge)
- Security vulnerabilities
- Bugs and logic errors
- Test failures
- Breaking changes
- Data corruption risks

### 🟠 MAJOR (SHOULD FIX - prevents tech debt)
- Missing error handling
- Performance issues
- Architectural problems
- **Consistency issues** (pattern/API/import/type inconsistencies)
- Code duplication
- Incorrect abstractions

### 🟡 MINOR (FIX NOW - avoid tech debt)
- Missing documentation
- Missing tests
- Unused imports/code
- Type hints missing
- Edge cases not handled
- Unclear variable names (when impacting readability)

### ⚪ NITPICKS (SKIP for dev, defer to release)
- Trivial naming preferences ("userData" vs "data")
- Comment wording
- Whitespace/formatting (if linter doesn't catch)
- Minor style preferences

---

## Execution Steps

1. **Fetch PR data** using the pr-review skill:
   ```bash
   # Fetch ALL PR data from 4 endpoints (reviews, inline comments, PR comments, issue comments)
   PR_DATA=$(~/.claude/skills/pr-review/fetch-pr-data <PR#> 2>/dev/null)

   # Extract specific comment types for analysis
   REVIEWS=$(echo "$PR_DATA" | jq '.reviews')
   INLINE_COMMENTS=$(echo "$PR_DATA" | jq '.inline_comments')
   PR_COMMENTS=$(echo "$PR_DATA" | jq '.pr_comments')
   ISSUE_COMMENTS=$(echo "$PR_DATA" | jq '.issue_comments')

   # Get last commit SHA
   git log -1 --format='%H'
   ```

   **WHY THE pr-review SKILL**:
   - Fetches from **all 4 endpoints** in parallel (1-2 seconds total)
   - Prevents missing comments (especially Claude Code bot reviews in issue comments)
   - Returns structured JSON with all feedback categorized
   - Handles errors gracefully with empty arrays

   **DATA STRUCTURE**:
   ```json
   {
     "reviews": [],           // Formal PR reviews (approve/request changes)
     "inline_comments": [],   // File:line specific code comments
     "pr_comments": [],       // PR conversation thread
     "issue_comments": []     // WHERE CLAUDE CODE BOT POSTS!
   }
   ```

   **AGENT WARNING**: Always use the pr-review skill to avoid missing comments!

2. **Parse and categorize** all comments from the 4 arrays using these keyword patterns:
   - **Critical**: "critical", "security", "vulnerability", "bug", "breaks", "fails", "test failure", "⚠️ Potential issue.*🔴 Critical"
   - **Major**: "major", "issue", "problem", "inconsistent", "inconsistency", "pattern", "should fix", "violates convention", "mixing", "🔴 Critical", "🟠 Major"
   - **Minor**: "minor", "missing", "should add", "consider adding", "edge case", "unclear", "🟡 Minor"
   - **Nitpick**: "nitpick", "nit:", "style", "consider renaming", "could be", "optional", "🧹 Nitpick"

   **Parse from**:
   - `reviews[].body` - Formal review text
   - `inline_comments[].body` - Code-specific feedback (include file:line context)
   - `pr_comments[].body` - Discussion thread feedback
   - `issue_comments[].body` - **Claude Code bot comprehensive reviews!**

3. **Filter recent comments**: Focus on comments created after the last commit (if applicable)

4. **Output format**:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PR DEV REVIEW - Development Priority Issues
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 CRITICAL ISSUES (X) - Must fix before merge:

1. [File:Line] Description
   → Fix: Specific actionable suggestion
   Status: ❌ Unaddressed / ✅ Fixed in commit ABC

2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟠 MAJOR ISSUES (Y) - Fix to prevent tech debt:

1. [File:Line] Description
   → Fix: Specific actionable suggestion
   Reason: Why this creates tech debt

2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟡 MINOR ISSUES (Z) - Fix now to maintain quality:

1. [File:Line] Description
   → Fix: Specific actionable suggestion

2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 SUMMARY:
- Total actionable: X critical + Y major + Z minor = N issues
- Nitpicks skipped: M (run /pr-release-ready for full review)
- Comments analyzed: P total from skill output (use `summary.total_all_comments`)
  - Reviews: `summary.total_reviews`
  - Inline: `summary.total_inline_comments`
  - PR thread: `summary.total_pr_comments`
  - Issue: `summary.total_issue_comments` (Claude bot reviews!)

💡 NEXT STEPS:
1. ⚠️ Address all X critical issues FIRST (blocking merge)
2. 🔧 Fix Y major issues (consistency, architecture, error handling)
3. 📝 Clean up Z minor issues (docs, tests, unused code)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

5. **Provide context**: For each issue, explain:
   - Why it matters (especially for major/minor)
   - How it creates tech debt if left unfixed
   - Suggested approach to fix

6. **Track status**: Check if issues have been addressed in recent commits by:
   - Comparing comment timestamps with commit timestamps
   - Looking for related changes in recent commit diffs
   - Marking items as ✅ Fixed, ⚠️ Partially addressed, or ❌ Unaddressed

## Special Instructions

- **Always use pr-review skill**: Call `~/.claude/skills/pr-review/fetch-pr-data <PR#>` to ensure no comments are missed
- **Prioritize actionability**: Every item should have a clear fix suggestion
- **Be specific**: Include file paths, line numbers, and exact changes needed
- **Focus on dev priorities**: Skip pure cosmetic items (covered by /pr-release-ready)
- **Consistency is MAJOR**: Treat all consistency issues as major tech debt
- **Include bot reviews**: CodeRabbit and Claude Code bot reviews contain valuable feedback
- **Parse all 4 arrays**: reviews, inline_comments, pr_comments, issue_comments (don't skip any!)
"
```
