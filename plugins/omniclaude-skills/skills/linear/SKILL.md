---
name: linear
description: Create, update, list, and manage Linear tickets with requirements and definition of done
version: 1.0.0
category: project-management
triggers:
  - "create Linear ticket"
  - "create ticket"
  - "Linear issue"
  - "update ticket"
  - "list tickets"
  - "get ticket"
  - "track task"
tags:
  - linear
  - tickets
  - project-management
  - tracking
author: OmniClaude Team
dependencies:
  - Linear MCP server
  - gh (GitHub CLI) - for PR integration
---

# Linear Ticket Management

Comprehensive ticket management for Linear with automatic requirements and definition of done tracking.

## 🚨 CRITICAL: ALWAYS DISPATCH TO POLYMORPHIC AGENT

**DO NOT run bash scripts or MCP tools directly.** When this skill is invoked, you MUST dispatch to a polymorphic-agent.

### ❌ WRONG - Running tools directly:
```
Bash(./create-ticket "Fix bug")
mcp__linear-server__create_issue(...)
```

### ✅ CORRECT - Dispatch to polymorphic-agent:
```
Task(
  subagent_type="polymorphic-agent",
  description="Create Linear ticket for bug fix",
  prompt="Create a Linear ticket for the following:
    Title: Fix authentication bug in login flow
    Priority: High
    Team: Engineering

    Use Linear MCP tools or skill scripts:
    - ./create-ticket
    - mcp__linear-server__create_issue

    Include:
    - Requirements section
    - Definition of Done
    - Appropriate labels and priority"
)
```

**WHY**: Polymorphic agents have full ONEX capabilities, intelligence integration, quality gates, and proper observability. Running tools directly bypasses all of this.

## Skills Available

This skill package provides 5 sub-skills:

1. **create-ticket** - Create new Linear tickets with requirements and DoD
2. **update-ticket** - Update existing tickets with status, requirements, or DoD
3. **list-tickets** - List and filter tickets by team, assignee, status
4. **get-ticket** - Get complete ticket details including requirements and DoD
5. **pr_integration.py** - Create tickets from PR review data (Pydantic-backed)

## When to Use

- Creating tasks from planning documents (e.g., EVENT_ALIGNMENT_PLAN.md)
- Tracking implementation progress with clear requirements
- Managing sprint workflows with definition of done criteria
- Organizing work with priority-based categorization

## Quick Start

```bash
# Create a ticket
./create-ticket "Implement DLQ for agent events" \
  --team "Engineering" \
  --priority "high" \
  --requirements "Must handle retry logic|Must sanitize secrets|Must log to PostgreSQL" \
  --dod "Unit tests passing|Integration tests passing|Documentation updated"

# List tickets
./list-tickets --team "Engineering" --state "In Progress"

# Update ticket status
./update-ticket TEAM-123 --state "In Progress"

# Get ticket details
./get-ticket TEAM-123
```

## Ticket Requirements

All tickets created through this skill will include:

### 1. Requirements Section
- Functional requirements (what needs to be built)
- Technical requirements (how it should be built)
- Constraints (what limitations exist)
- Dependencies (what must exist first)

### 2. Definition of Done
- Code quality gates (tests, linting, type checking)
- Documentation (README, API docs, code comments)
- Review criteria (PR review checklist)
- Deployment verification (health checks, monitoring)

### 3. Priority Classification
- **Critical**: Must be addressed before merge (blocking issues)
- **Major**: Should be addressed before merge (important issues)
- **Minor**: Should be addressed but not blocking (nice-to-haves)
- **Nit**: Optional improvements (can be deferred)

## Labels

Standard labels automatically applied:
- `has-requirements` - Ticket includes requirements section
- `has-dod` - Ticket includes definition of done
- `priority:<level>` - Priority level (critical, major, minor, nit)

## Integration with Planning Documents

When creating tickets from planning documents like EVENT_ALIGNMENT_PLAN.md:

1. Extract task information (title, description, phase)
2. Convert to structured requirements
3. Generate definition of done from acceptance criteria
4. Set priority based on phase importance
5. Link to parent epic/milestone

## PR Review Integration

The `pr_integration.py` module provides type-safe integration with the Pydantic-backed PR review system. This ensures Claude bot comments are **NEVER missed** when creating Linear tickets from PR reviews.

### Why This Matters

Claude Code bot posts reviews to the **issue_comments** endpoint, which is often missed by simple PR review tools. The PR integration uses a 4-endpoint fetcher that guarantees complete coverage:

1. `/pulls/{pr}/reviews` - Formal reviews
2. `/pulls/{pr}/comments` - Inline code comments
3. `gh pr view --json comments` - PR conversation
4. `/issues/{pr}/comments` - **Where Claude bot posts!**

### Quick Start

```bash
# Get all critical/major issues for Linear tickets
./pr_integration.py 123

# Only Claude bot comments (prioritized)
./pr_integration.py 123 --claude-only

# Critical issues + Claude comments
./pr_integration.py 123 --critical-only

# Check merge status
./pr_integration.py 123 --status-only

# Human-readable summary
./pr_integration.py 123 --format summary
```

### Python API

```python
from pr_integration import get_pr_issues_for_linear, get_merge_status_for_linear

# Get issues ready for Linear API
issues = get_pr_issues_for_linear(
    pr_number=123,
    repo="owner/repo",        # Optional, auto-detected
    include_claude=True,      # Always include Claude (default)
    include_critical=True,    # Include critical issues
    include_major=True,       # Include major issues
    include_minor=False,      # Exclude minor by default
)

# Each issue is ready for mcp__linear-server__create_issue:
for issue in issues:
    # Use directly with Linear MCP
    mcp__linear-server__create_issue(
        title=issue["title"],
        description=issue["description"],
        priority=issue["priority"],
        labels=issue["labels"],
        team="Engineering",
    )

# Check merge readiness
status = get_merge_status_for_linear(123)
if status["can_merge"]:
    print("Ready to merge!")
else:
    print(f"Blocked by {status['blocker_count']} issues")
```

### Output Format

Each issue dict contains:

| Field | Type | Description |
|-------|------|-------------|
| `title` | str | Formatted title with PR reference |
| `description` | str | Full markdown description |
| `priority` | int | Linear priority (1=Urgent, 2=High, 3=Normal, 4=Low) |
| `labels` | list[str] | Severity and type labels |
| `source_comment_id` | str | GitHub comment ID |
| `source_pr` | int | PR number |
| `source_author` | str | Comment author |
| `is_claude_comment` | bool | True if from Claude bot |
| `severity` | str | critical/major/minor/nitpick |
| `file_path` | str|None | File path if inline comment |
| `file_line` | int|None | Line number if inline comment |

### Priority Mapping

| PR Severity | Linear Priority | Description |
|-------------|-----------------|-------------|
| CRITICAL | 1 (Urgent) | Security, crashes, data loss |
| MAJOR | 2 (High) | Bugs, performance, missing tests |
| MINOR | 3 (Normal) | Code quality, documentation |
| NITPICK | 4 (Low) | Style, formatting, naming |

## MCP Integration

This skill uses the Linear MCP server for all API operations. Linear MCP is retained because:
- Linear API is external third-party service (not OmniNode infrastructure)
- MCP provides type-safe, validated API access
- No need for event-based integration for external ticket management

Ensure Linear MCP is connected:

```bash
# Check MCP connection
/mcp

# Should show: Connected to linear-server
```

**Architecture Note**: While OmniNode internal services (intelligence, routing, observability) use event-based communication via Kafka, external integrations like Linear continue to use MCP for simplicity and type safety.

## Skills Location

**Claude Code Access**: `./`
**Executables**:
- `./create-ticket`
- `./update-ticket`
- `./list-tickets`
- `./get-ticket`
- `./pr_integration.py` (Pydantic-backed PR integration)

## See Also

- Linear MCP tools (mcp__linear-server__*)
- Event alignment plan: `/docs/events/EVENT_ALIGNMENT_PLAN.md`
- PR review skills: `../pr-review/`
