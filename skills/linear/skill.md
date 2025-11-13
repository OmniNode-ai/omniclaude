---
name: linear-ticket-management
description: Create, update, list, and manage Linear tickets with requirements and definition of done
---

# Linear Ticket Management

Comprehensive ticket management for Linear with automatic requirements and definition of done tracking.

## Skills Available

This skill package provides 4 sub-skills:

1. **create-ticket** - Create new Linear tickets with requirements and DoD
2. **update-ticket** - Update existing tickets with status, requirements, or DoD
3. **list-tickets** - List and filter tickets by team, assignee, status
4. **get-ticket** - Get complete ticket details including requirements and DoD

## When to Use

- Creating tasks from planning documents (e.g., EVENT_ALIGNMENT_PLAN.md)
- Tracking implementation progress with clear requirements
- Managing sprint workflows with definition of done criteria
- Organizing work with priority-based categorization

## Quick Start

```bash
# Create a ticket
~/.claude/skills/linear/create-ticket "Implement DLQ for agent events" \
  --team "Engineering" \
  --priority "high" \
  --requirements "Must handle retry logic|Must sanitize secrets|Must log to PostgreSQL" \
  --dod "Unit tests passing|Integration tests passing|Documentation updated"

# List tickets
~/.claude/skills/linear/list-tickets --team "Engineering" --state "In Progress"

# Update ticket status
~/.claude/skills/linear/update-ticket TEAM-123 --state "In Progress"

# Get ticket details
~/.claude/skills/linear/get-ticket TEAM-123
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

**Claude Code Access**: `~/.claude/skills/linear/`
**Executables**:
- `~/.claude/skills/linear/create-ticket`
- `~/.claude/skills/linear/update-ticket`
- `~/.claude/skills/linear/list-tickets`
- `~/.claude/skills/linear/get-ticket`

## See Also

- Linear MCP tools (mcp__linear-server__*)
- Event alignment plan: `/docs/events/EVENT_ALIGNMENT_PLAN.md`
- PR review skills: `~/.claude/skills/pr-review/`
