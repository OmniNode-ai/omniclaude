---
name: create-followup-tickets
description: Create Linear tickets from code review issues found in the current session
version: 1.0.0
category: workflow
tags:
  - linear
  - tickets
  - review
  - batch
  - automation
author: OmniClaude Team
---

# Create Follow-up Tickets Skill

Create Linear tickets in batch from code review output. This skill reads review data from the current session context and creates tickets for unresolved issues.

## When to Use

Use this skill after running a code review:
- After `/local-review` completes with issues
- After `/pr-review-dev` identifies follow-up work
- After any review that produces structured issue output

## Quick Start

```bash
# After running a review, create follow-up tickets
/create-followup-tickets "beta hardening"
```

## Review Data Format

The skill expects review data in this JSON structure (output by `/local-review` and `/pr-review-dev`):

```json
{
  "critical": [
    {"file": "src/api.py", "line": 45, "description": "SQL injection vulnerability", "keyword": "injection"}
  ],
  "major": [
    {"file": "src/auth.py", "line": 89, "description": "Missing password validation", "keyword": "missing validation"}
  ],
  "minor": [
    {"file": "src/config.py", "line": 12, "description": "Magic number should be constant", "keyword": "should"}
  ],
  "nit": [
    {"file": "src/models.py", "line": 56, "description": "Unused import", "keyword": "style"}
  ]
}
```

## Project Fuzzy Matching

The first argument is matched against Linear project names:

| Input | Matches |
|-------|---------|
| "beta hardening" | "Beta - OmniNode Platform Hardening" |
| "beta demo" | "Beta Demo - January 2026" |
| "workflow" | "Workflow Automation" |

If multiple projects match, you'll be prompted to select one.

## Severity Filtering

| Flag | Issues Included |
|------|-----------------|
| (default) | Critical, Major, Minor |
| `--include-nits` | Critical, Major, Minor, Nit |
| `--only-major` | Critical, Major |
| `--only-critical` | Critical only |

## Auto Repository Labeling

By default, the current repository is detected and added as a label:

```bash
# In omniclaude repo
/create-followup-tickets "beta hardening"
# → Labels: [critical, from-review, omniclaude]
```

Override with `--repo` or disable with `--no-repo-label`.

## Ticket Format

Each created ticket follows this format:

**Title**: `[SEVERITY] Description (file:line)`

**Description**:
```markdown
## Review Issue

**Severity**: MAJOR
**Keyword**: `missing validation`
**Source**: Code review follow-up

## Details

Missing password validation in authentication flow.

## Location

- **File**: `src/auth.py`
- **Line**: 89

## Definition of Done

- [ ] Issue addressed in code
- [ ] Tests added/updated if applicable
- [ ] PR created and reviewed
```

**Priority Mapping**:
| Severity | Linear Priority |
|----------|-----------------|
| Critical | 1 (Urgent) |
| Major | 2 (High) |
| Minor | 3 (Normal) |
| Nit | 4 (Low) |

## Modes

### Preview Mode (`--dry-run`)

Shows what tickets would be created without actually creating them:

```bash
/create-followup-tickets "beta hardening" --dry-run
```

### Auto Mode (`--auto`)

Creates all tickets without confirmation:

```bash
/create-followup-tickets "beta hardening" --auto
```

### Interactive Mode (default)

Shows preview and asks for confirmation before creating.

## Parent Linking

Link all created tickets to a parent issue:

```bash
/create-followup-tickets "beta hardening" --parent OMN-1850
```

This creates an epic relationship where all follow-up tickets are children of the parent.

## Fallback: File Input

If no review data is in the session, provide a file:

```bash
/create-followup-tickets "beta hardening" --from-file ./tmp/pr-review-78.md
```

Supported formats:
- JSON (`.json`) - Direct review output
- Markdown (`.md`) - Review report with issue sections

## Integration with Review Commands

### Typical Workflow

```bash
# 1. Run local review
/local-review

# Review shows:
# - 2 Critical issues
# - 3 Major issues
# - 1 Minor issue

# 2. Create follow-up tickets for remaining work
/create-followup-tickets "beta hardening"

# 3. Tickets created and linked to project
```

### PR Review Workflow

```bash
# 1. Review a PR
/pr-review-dev 78

# 2. Fix what you can in this session

# 3. Create tickets for remaining items
/create-followup-tickets "beta hardening" --only-major
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No review data | Suggests running a review first |
| No matching project | Lists available projects |
| Ticket creation fails | Continues with remaining tickets, reports failures |
| Invalid file path | Reports file not found |

## See Also

- `/local-review` - Review local changes
- `/pr-review-dev` - Review a PR
- `/create-ticket` - Create a single ticket
- Linear skills: `${CLAUDE_PLUGIN_ROOT}/skills/linear/`
