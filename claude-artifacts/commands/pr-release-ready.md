# PR Release Ready - Comprehensive Pre-Merge Review

**Purpose**: Verify PR is production-ready with all feedback addressed, including polish items.

**Philosophy**: Nothing ships with known issues. All feedback should be addressed or explicitly documented as acceptable.

---

## Execution

Use the Task tool to dispatch to the polymorphic agent for comprehensive PR analysis:

```
description: "Comprehensive PR release readiness assessment"
subagent_type: "polymorphic-agent"
prompt: "Execute a comprehensive release-ready PR review with the following requirements:

## PR Release Readiness Task

Perform a thorough production-readiness assessment covering ALL feedback categories.

**User will provide**: PR number (e.g., "18") or full GitHub PR URL

### 🔴 CRITICAL (X issues)
- Security vulnerabilities
- Bugs and logic errors
- Test failures
- Breaking changes
- Data corruption risks

### 🟠 MAJOR (Y issues)
- Missing error handling
- Performance issues
- Architectural problems
- **Consistency issues** (pattern/API/import/type inconsistencies)
- Code duplication
- Incorrect abstractions

### 🟡 MINOR (Z issues)
- Missing documentation
- Missing tests
- Unused imports/code
- Type hints missing
- Edge cases not handled
- Unclear variable names

### ⚪ NITPICKS/POLISH (N issues)
- Naming preferences
- Comment improvements
- Formatting/style suggestions
- Optional refactorings
- Documentation polish

---

## Execution Steps

1. **Fetch ALL PR feedback** using the pr-review skill:
   ```bash
   # Fetch ALL PR data from 4 endpoints (reviews, inline comments, PR comments, issue comments)
   PR_DATA=$(~/.claude/skills/pr-review/fetch-pr-data <PR#> 2>/dev/null)

   # Extract specific comment types for analysis
   REVIEWS=$(echo "$PR_DATA" | jq '.reviews')
   INLINE_COMMENTS=$(echo "$PR_DATA" | jq '.inline_comments')
   PR_COMMENTS=$(echo "$PR_DATA" | jq '.pr_comments')
   ISSUE_COMMENTS=$(echo "$PR_DATA" | jq '.issue_comments')

   # Get summary counts
   TOTAL_COMMENTS=$(echo "$PR_DATA" | jq '.summary.total_all_comments')

   # Get PR metadata
   gh pr view <PR#> --json title,body,author,state,number,url,commits

   # Get last commit details
   git log -1 --format='%H %s %ai'
   ```

   **WHY THE pr-review SKILL**:
   - Fetches from **all 4 endpoints** in parallel (1-2 seconds total)
   - Prevents missing comments (especially Claude Code bot reviews in issue comments)
   - Returns structured JSON with all feedback categorized
   - Handles errors gracefully with empty arrays
   - Provides summary counts automatically

   **DATA STRUCTURE**:
   ```json
   {
     "reviews": [],           // Formal PR reviews (approve/request changes)
     "inline_comments": [],   // File:line specific code comments
     "pr_comments": [],       // PR conversation thread
     "issue_comments": [],    // WHERE CLAUDE CODE BOT POSTS!
     "summary": {
       "total_all_comments": N
     }
   }
   ```

   **AGENT WARNING**: Always use the pr-review skill to avoid missing comments!

2. **Categorize comprehensively** with PRIORITY ORDER (most important first):

   **PRIORITY 1 - Structured Recommendations** (from Claude bot in issue comments):
   - Look for sections like "Must Fix Before Merge", "Should Fix Before Production", "Recommendations"
   - These are ALWAYS critical/major regardless of keywords
   - Common patterns:
     - `❗` or `### **Must Fix**` or `**Must Fix Before Merge**` → CRITICAL
     - `⚠️` or `### **Should Fix**` or `**Should Fix Before Production**` → MAJOR
     - `💡` or `### **Nice to Have**` → MINOR (unless security/architecture related)

   **PRIORITY 2 - Emoji/Section Markers** (structured feedback):
   - 🔴 or "### Critical" or "MUST FIX" → CRITICAL
   - 🟠 or "### Major" or "SHOULD FIX" → MAJOR
   - 🟡 or "### Minor" or "FIX NOW" → MINOR
   - ⚪ or "### Nitpick" or "OPTIONAL" → NITPICK

   **PRIORITY 3 - Keyword Patterns** (inline/unstructured feedback):
   - **Critical**: "security", "vulnerability", "bug", "breaks", "fails", "test failure", "data corruption", "production blocker"
   - **Major**: "architecture", "inconsistent", "pattern", "violates convention", "error handling", "performance issue", "authentication", "service discovery"
   - **Minor**: "missing documentation", "missing test", "consider adding", "edge case", "type hint", "unclear"
   - **Nitpick**: "nitpick", "nit:", "style", "consider renaming", "optional", "refactor suggestion"

   **⚠️ CRITICAL PARSING RULE**:
   Parse `issue_comments[]` FIRST (Claude bot) before other sources. Claude bot's structured recommendations in issue comments take precedence over all inline comments. Architectural and security concerns are ALWAYS major/critical even if phrased politely.

   **Parse from** (in priority order):
   1. `issue_comments[].body` - **Claude Code bot comprehensive reviews with structured recommendations!**
   2. `reviews[].body` - Formal review text (CodeRabbit summaries)
   3. `pr_comments[].body` - Discussion thread feedback
   4. `inline_comments[].body` - Code-specific feedback (file:line context)

3. **Track resolution status**: For EACH issue, determine:
   - ✅ **Fixed**: Code changed in recent commits addressing the issue
   - ⚠️ **Partially addressed**: Some but not all aspects fixed
   - 📝 **Documented as deferred**: Explicitly noted as acceptable/future work
   - ❌ **Unaddressed**: No changes made

4. **Output format**:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PR RELEASE READINESS REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PR: #<num> - <title>
Author: <author>
Status: <state>
Last commit: <sha> (<timestamp>)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 CRITICAL ISSUES (X):

[ ] 1. [File:Line] Description
    → Fix: Specific actionable suggestion
    Status: ❌ Unaddressed / ✅ Fixed in commit ABC123
    Blocker: YES - must be resolved before merge

[ ] 2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟠 MAJOR ISSUES (Y):

[ ] 1. [File:Line] Description
    → Fix: Specific actionable suggestion
    Status: ❌ Unaddressed / ✅ Fixed / ⚠️ Partially addressed
    Impact: Tech debt, maintainability, consistency

[ ] 2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟡 MINOR ISSUES (Z):

[ ] 1. [File:Line] Description
    → Fix: Specific actionable suggestion
    Status: ❌ Unaddressed / ✅ Fixed / 📝 Documented as deferred
    Impact: Code quality, documentation completeness

[ ] 2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚪ NITPICKS/POLISH (N):

[ ] 1. [File:Line] Description
    → Suggestion: Optional improvement
    Status: ❌ Unaddressed / ✅ Applied / 📋 Deferred (acceptable)
    Impact: Polish, code style

[ ] 2. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 RELEASE READINESS SUMMARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Critical:  X/X fixed (100% required) ✅/❌
Major:     Y/Y fixed (100% required) ✅/❌
Minor:     A/Z fixed (100% required) ✅/❌
Nitpicks:  M/N fixed (optional, but recommended)

Total feedback items: <count>
├─ Fully addressed: <count> (<percent>%)
├─ Partially addressed: <count>
├─ Deferred (documented): <count>
└─ Unaddressed: <count> ⚠️

Comments analyzed (from skill summary):
├─ Formal reviews: `summary.total_reviews`
├─ Inline comments: `summary.total_inline_comments`
├─ PR thread: `summary.total_pr_comments`
├─ Issue comments (Claude bot!): `summary.total_issue_comments`
└─ Total: `summary.total_all_comments`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 MERGE CHECKLIST:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[ ] All critical issues resolved (0 remaining)
[ ] All major issues fixed (0 remaining)
[ ] All minor issues addressed (0 remaining)
[ ] Nitpicks applied OR documented as acceptable
[ ] All tests passing
[ ] Documentation updated
[ ] CHANGELOG/release notes updated (if applicable)
[ ] Breaking changes documented (if applicable)
[ ] Pre-commit hooks passing
[ ] No merge conflicts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ MERGE RECOMMENDATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Status: [✅ READY TO MERGE / ⚠️ READY WITH CAVEATS / ❌ NOT READY]

Rationale:
<Explain merge readiness status with specific details about:
- Critical blockers resolved or remaining
- Major issues status and impact
- Minor issues status and justification if deferred
- Overall code quality assessment
- Risk assessment for shipping as-is>

Deferred Items (if any):
<List any items explicitly deferred with clear justification:
- [Category] Item description - Reason for deferral
- Expected timeline for addressing deferred items (if applicable)>

Conditions for merge (if caveats):
<If ready with caveats, list specific conditions that must be met>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

5. **Resolution tracking**: For each item, actively check:
   - Compare comment timestamps with commit history
   - Search recent commit diffs for related file/line changes
   - Look for explicit resolution comments or status updates
   - Verify test passage if tests were mentioned

6. **Provide actionable guidance**:
   - **For unaddressed issues**: Specific steps to resolve
   - **For partially addressed**: What's missing and why it matters
   - **For deferred items**: Explicit documentation of deferral rationale

7. **Make a clear recommendation**:
   - **READY TO MERGE**: All critical/major/minor issues resolved, nitpicks acceptable
   - **READY WITH CAVEATS**: Specific conditions listed for merge
   - **NOT READY**: Clear blockers identified with remediation steps

## Special Instructions

- **Always use pr-review skill**: Call `~/.claude/skills/pr-review/fetch-pr-data <PR#>` to ensure no comments are missed
- **⚠️ PRIORITY ORDER IS CRITICAL**: Parse issue_comments[] FIRST (Claude bot structured recommendations), then reviews[], then pr_comments[], then inline_comments[]
- **Structured sections override keywords**: If Claude bot has "Must Fix Before Merge" section, those items are CRITICAL regardless of keywords used
- **Architectural/security concerns are MAJOR/CRITICAL**: Even if phrased politely, concerns about authentication, service discovery, TLS, database migrations, rollback procedures, etc. are MAJOR or CRITICAL issues
- **Don't downgrade based on tone**: "Consider adding authentication" is still MAJOR/CRITICAL if it's about security
- **Be comprehensive**: Include EVERYTHING, even resolved items (show ✅ status)
- **Be specific**: Every issue needs file:line and exact fix suggestion
- **Be decisive**: Provide clear merge recommendation with rationale
- **Consistency is CRITICAL**: Treat consistency issues as major blockers
- **Track status actively**: Don't assume - verify by checking commits
- **Document deferrals**: If anything is deferred, it must be explicitly documented
- **Parse all 4 arrays**: reviews, inline_comments, pr_comments, issue_comments (don't skip any!)

## Differences from /pr-dev-review

- **Scope**: ALL feedback including nitpicks (vs. dev review skips nitpicks)
- **Status tracking**: Track resolution status for every item
- **Merge decision**: Provide clear GO/NO-GO recommendation
- **Completeness**: Show resolved items too (not just outstanding)
- **Release focus**: Production readiness vs. development priorities
"
```
