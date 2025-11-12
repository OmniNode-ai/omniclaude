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

2. **Parse and categorize** with PRIORITY ORDER (most important first):

   **PRIORITY 1 - Structured Recommendations** (from Claude bot in issue comments):
   - Look for sections like "Must Fix Before Merge", "Should Fix Before Production", "Recommendations"
   - These are ALWAYS critical/major regardless of keywords
   - Common patterns:
     - `❗` or `### **Must Fix**` → CRITICAL
     - `⚠️` or `### **Should Fix**` → MAJOR
     - `💡` or `### **Nice to Have**` → MINOR (unless security/architecture related)

   **PRIORITY 2 - Emoji/Section Markers** (structured feedback):
   - 🔴 or "### Critical" or "MUST FIX" → CRITICAL
   - 🟠 or "### Major" or "SHOULD FIX" → MAJOR
   - 🟡 or "### Minor" or "FIX NOW" → MINOR
   - ⚪ or "### Nitpick" or "OPTIONAL" → NITPICK

   **PRIORITY 3 - Keyword Patterns** (inline/unstructured feedback):
   - **Critical**: "security", "vulnerability", "bug", "breaks", "fails", "test failure", "data corruption"
   - **Major**: "architecture", "inconsistent", "pattern", "violates convention", "error handling", "performance issue"
   - **Minor**: "missing documentation", "missing test", "consider adding", "edge case", "type hint"
   - **Nitpick**: "nitpick", "nit:", "style", "consider renaming", "optional"

   **⚠️ CRITICAL PARSING RULE**:
   Parse `issue_comments[]` FIRST (Claude bot) before other sources. Claude bot's structured recommendations in issue comments take precedence over all inline comments.

   **Parse from** (in priority order):
   1. `issue_comments[].body` - **Claude Code bot comprehensive reviews with structured recommendations!**
   2. `reviews[].body` - Formal review text (CodeRabbit summaries)
   3. `pr_comments[].body` - Discussion thread feedback
   4. `inline_comments[].body` - Code-specific feedback (file:line context)

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
- **⚠️ PRIORITY ORDER IS CRITICAL**: Parse issue_comments[] FIRST (Claude bot structured recommendations), then reviews[], then pr_comments[], then inline_comments[]
- **Structured sections override keywords**: If Claude bot has "Must Fix Before Merge" section, those items are CRITICAL regardless of keywords used
- **Architectural/security concerns are MAJOR**: Even if phrased politely, concerns about authentication, service discovery, TLS, database migrations, etc. are MAJOR issues
- **Don't downgrade based on tone**: "Consider adding authentication" is still MAJOR if it's about security
- **Prioritize actionability**: Every item should have a clear fix suggestion
- **Be specific**: Include file paths, line numbers, and exact changes needed
- **Focus on dev priorities**: Skip pure cosmetic items (covered by /pr-release-ready)
- **Consistency is MAJOR**: Treat all consistency issues as major tech debt
- **Parse all 4 arrays**: reviews, inline_comments, pr_comments, issue_comments (don't skip any!)
"
```
