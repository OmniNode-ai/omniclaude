---
name: fetch-pr-data
description: Fetch all PR review data from GitHub (4 endpoints) - reviews, inline comments, PR comments, and issue comments where Claude Code bot posts
---

# Fetch PR Review Data

Comprehensive PR review data fetcher that queries **all 4 GitHub API endpoints** where PR feedback can appear.

## Why 4 Endpoints?

GitHub distributes PR feedback across multiple endpoints:

1. **Reviews API** (`/pulls/{pr}/reviews`) - Formal PR reviews (Approve/Request Changes/Comment)
2. **Pull Comments API** (`/pulls/{pr}/comments`) - Inline code comments (file:line specific)
3. **PR Comments API** (`/pulls/{pr}` via gh pr view) - PR conversation thread
4. **Issue Comments API** (`/issues/{pr}/comments`) - **WHERE CLAUDE CODE BOT POSTS!**

**Critical**: Many bots (including Claude Code bot, CodeRabbit, etc.) post comprehensive reviews as **issue comments**, not PR comments. If you skip this endpoint, you'll miss these reviews!

## When to Use

- Before analyzing PR feedback
- Before creating PR review summaries
- When checking PR merge readiness
- When you need complete PR feedback context
- Anytime you need to ensure no comments are missed

## Usage

Use the Bash tool to execute:

```bash
~/.claude/skills/pr-review/fetch-pr-data <PR_NUMBER>
```

### Arguments

- `PR_NUMBER` - PR number (e.g., `20`) or full GitHub URL (e.g., `https://github.com/OmniNode-ai/omniclaude/pull/20`)

### Examples

```bash
# By PR number
~/.claude/skills/pr-review/fetch-pr-data 20

# By GitHub URL
~/.claude/skills/pr-review/fetch-pr-data https://github.com/OmniNode-ai/omniclaude/pull/20
```

## Output Format

Returns a JSON object with all PR feedback:

```json
{
  "pr_number": 20,
  "repository": "OmniNode-ai/omniclaude",
  "fetched_at": "2025-11-04T12:00:00Z",
  "reviews": [
    {
      "author": "coderabbitai[bot]",
      "state": "COMMENTED",
      "body": "Review body...",
      "submitted_at": "2025-11-01T16:30:54Z",
      "id": 123456
    }
  ],
  "inline_comments": [
    {
      "author": "coderabbitai[bot]",
      "path": "agents/lib/agent_router.py",
      "line": 77,
      "body": "Hardcoded path warning...",
      "created_at": "2025-11-01T16:31:00Z",
      "id": 123457
    }
  ],
  "pr_comments": [
    {
      "author": "jonah",
      "body": "Good catch!",
      "created_at": "2025-11-01T17:00:00Z",
      "id": 123458
    }
  ],
  "issue_comments": [
    {
      "author": "claude[bot]",
      "body": "# Pull Request Review: Phase 2...\n\n## Critical Issues\n...",
      "created_at": "2025-11-04T12:14:36Z",
      "id": 123459
    }
  ],
  "summary": {
    "total_reviews": 1,
    "total_inline_comments": 6,
    "total_pr_comments": 3,
    "total_issue_comments": 8,
    "total_all_comments": 18
  }
}
```

## Integration with Slash Commands

This skill is designed to be used by:
- `/pr-dev-review` - Development-focused PR review
- `/pr-release-ready` - Comprehensive pre-merge review

Instead of manually calling 4 separate GitHub API endpoints, slash commands can simply call this skill and parse the returned JSON.

## Example Workflow

```bash
# Step 1: Fetch all PR data using this skill
PR_DATA=$(~/.claude/skills/pr-review/fetch-pr-data 20)

# Step 2: Parse specific comment types
ISSUE_COMMENTS=$(echo "$PR_DATA" | jq '.issue_comments')
CLAUDE_BOT_REVIEWS=$(echo "$PR_DATA" | jq '.issue_comments[] | select(.author == "claude[bot]")')

# Step 3: Analyze and categorize feedback
# ... (PR review logic) ...
```

## Performance

- **Parallel Fetching**: All 4 endpoints queried concurrently
- **Typical Runtime**: 1-2 seconds for complete fetch
- **Caching**: None (always fetches latest data)
- **Rate Limits**: Respects GitHub API limits

## Dependencies

Required tools (install with `brew install gh jq`):
- `gh` - GitHub CLI (for API access)
- `jq` - JSON processor (for parsing responses)

## Error Handling

- **Missing dependencies**: Script checks and reports missing tools
- **Invalid PR number**: Validates input and provides helpful error
- **API failures**: Gracefully handles endpoint failures (returns empty arrays)
- **Repository detection**: Auto-detects current repository

## Common Pitfalls Avoided

❌ **Skipping issue comments** - Misses Claude Code bot and other bot reviews
❌ **Only checking PR comments** - Misses inline code comments
❌ **Only checking reviews API** - Misses discussion thread feedback
❌ **Sequential fetching** - Slow (this skill fetches in parallel)

✅ **This skill fetches ALL 4 endpoints** - Nothing is missed
✅ **Parallel execution** - Fast results
✅ **Structured output** - Easy to parse and analyze

## Skills Location

**Claude Code Access**: `~/.claude/skills/pr-review/`
**Executable**: `~/.claude/skills/pr-review/fetch-pr-data`

## Notes

- **Always use this skill** when analyzing PR feedback to avoid missing comments
- **Claude Code bot** posts comprehensive reviews as issue comments (endpoint #4)
- **CodeRabbit** posts both inline comments (endpoint #2) and summary reviews (endpoint #4)
- **Parallel fetching** ensures fast results even for PRs with many comments
- **JSON output** makes it easy to filter and categorize comments programmatically

## Debugging

If you're not seeing expected comments:

```bash
# Run with verbose output
~/.claude/skills/pr-review/fetch-pr-data 20 | jq '.'

# Check each endpoint separately
~/.claude/skills/pr-review/fetch-pr-data 20 | jq '.issue_comments | length'  # Claude bot reviews
~/.claude/skills/pr-review/fetch-pr-data 20 | jq '.inline_comments | length' # Inline comments
~/.claude/skills/pr-review/fetch-pr-data 20 | jq '.reviews | length'         # Formal reviews
~/.claude/skills/pr-review/fetch-pr-data 20 | jq '.pr_comments | length'     # PR thread
```

## See Also

- `/pr-dev-review` - Development-focused PR review command
- `/pr-release-ready` - Comprehensive pre-merge review command
- GitHub API Docs: https://docs.github.com/en/rest/pulls
