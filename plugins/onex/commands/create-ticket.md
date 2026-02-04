---
name: create-ticket
description: Create a single Linear ticket from args, contract file, or plan milestone with conflict resolution
tags: [linear, tickets, automation]
args:
  - name: title
    description: Ticket title (mutually exclusive with --from-contract, --from-plan)
    required: false
  - name: from-contract
    description: Path to YAML contract file
    required: false
  - name: from-plan
    description: Path to plan markdown file
    required: false
  - name: milestone
    description: Milestone ID when using --from-plan (e.g., M4)
    required: false
  - name: repo
    description: Repository label (e.g., omniclaude, omnibase_core)
    required: false
  - name: parent
    description: Parent issue ID for epic relationship (e.g., OMN-1800)
    required: false
  - name: blocked-by
    description: Comma-separated issue IDs that block this ticket
    required: false
  - name: project
    description: Linear project name
    required: false
  - name: team
    description: Linear team name (default Omninode)
    required: false
    default: "Omninode"
  - name: allow-arch-violation
    description: Bypass architecture dependency validation (use with caution)
    required: false
---

# Create Linear Ticket

You are creating a Linear ticket with standardized format and conflict resolution.

**Announce at start:** "Creating Linear ticket from {source_type}."

---

## Argument Validation

### Mutual Exclusivity Check

These argument groups are **mutually exclusive**:
1. `--title` (direct title specification)
2. `--from-contract` (load from YAML contract file)
3. `--from-plan` + `--milestone` (extract from plan markdown)

If more than one group is provided, report error:
```
Error: Arguments are mutually exclusive. Provide ONE of:
  - --title "Ticket title"
  - --from-contract path/to/contract.yaml
  - --from-plan path/to/plan.md --milestone M4
```

### Required Combinations

- `--from-plan` requires `--milestone` (e.g., `--milestone M4`)
- If none of the three sources provided, report error:
```
Error: Must provide ticket source. Use ONE of:
  - --title "Ticket title"
  - --from-contract path/to/contract.yaml
  - --from-plan path/to/plan.md --milestone M4
```

---

## Source Parsing

### Option 1: Direct Title (`--title`)

When `--title` is provided:

```python
ticket_data = {
    "title": args.title,
    "repo": args.repo or get_current_repo(),
    "requirements": [],
    "verification": [],
    "context": {}
}
```

User will need to provide description interactively or via additional args.

### Option 2: Contract File (`--from-contract`)

Parse YAML contract file matching the ticket-work schema:

```python
def parse_contract_file(path: str) -> dict:
    """Parse YAML contract file for ticket data.

    Expected schema (from ticket-work skill):
    - ticket_id: optional (will be assigned by Linear)
    - title: required
    - repo: optional
    - requirements[]: list of {id, statement, rationale, acceptance[]}
    - verification[]: list of {id, title, kind, command, expected, blocking}
    - context: {relevant_files[], patterns_found[], notes}
    """
    import yaml
    from pathlib import Path

    content = Path(path).read_text()
    contract = yaml.safe_load(content)

    # Validate required fields
    if not contract.get("title"):
        raise ValueError(f"Contract missing required 'title' field: {path}")

    return {
        "title": contract["title"],
        "repo": contract.get("repo"),
        "requirements": contract.get("requirements", []),
        "verification": contract.get("verification", []),
        "context": contract.get("context", {})
    }
```

**Error handling:**
- File not found: Report path and suggest checking location
- YAML parse error: Show line number and syntax issue
- Missing title: Report validation error

### Option 3: Plan Milestone (`--from-plan` + `--milestone`)

Extract milestone from plan markdown:

```python
def parse_plan_milestone(path: str, milestone_id: str) -> dict:
    """Extract milestone from plan markdown.

    Milestones follow pattern: ## M\d+: Title
    Content until next ## heading is the description.
    """
    import re
    from pathlib import Path

    content = Path(path).read_text()

    # Pattern: ## M{N}: Title
    pattern = rf'^## ({milestone_id}):\s*(.+?)$'
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)

    if not match:
        available = re.findall(r'^## (M\d+):', content, re.MULTILINE)
        raise ValueError(
            f"Milestone {milestone_id} not found in {path}.\n"
            f"Available milestones: {', '.join(available) or 'none'}"
        )

    milestone_title = match.group(2).strip()
    start_pos = match.end()

    # Find next ## heading or end of file
    next_heading = re.search(r'^## ', content[start_pos:], re.MULTILINE)
    if next_heading:
        description = content[start_pos:start_pos + next_heading.start()].strip()
    else:
        description = content[start_pos:].strip()

    return {
        "title": f"{milestone_id}: {milestone_title}",
        "description": description,
        "repo": None,  # Will use --repo arg or current repo
        "requirements": [],
        "verification": [],
        "context": {}
    }
```

---

## Conflict Detection

Before creating, search for existing tickets with same title:

```
mcp__linear-server__list_issues(
    query="{ticket_title}",
    team="{team}",
    limit=10
)
```

### Exact Match Detection

Check if any returned issue has a title that matches (case-insensitive):

```python
def find_existing_ticket(issues: list, title: str) -> dict | None:
    """Find ticket with matching title."""
    normalized_title = title.lower().strip()
    for issue in issues:
        if issue.get("title", "").lower().strip() == normalized_title:
            return issue
    return None
```

### Conflict Resolution

If existing ticket found, use **AskUserQuestion** with options:

```
Found existing ticket "{existing_title}" ({existing_id}).

How would you like to proceed?
1. Update existing ticket (merge descriptions)
2. Cancel old ticket and create new
3. Skip this ticket
```

**Option 1: Update existing**
- Fetch existing description
- Merge with new description (append new sections)
- Call `mcp__linear-server__update_issue(id="{existing_id}", description="{merged}")`

**Option 2: Cancel and create new**
- Update existing to "Canceled" state
- Create new ticket with full description

**Option 3: Skip**
- Report skip and exit without changes

---

## Description Template

Generate standardized ticket description:

```markdown
## Summary

{summary_from_title_or_context}

**Repository**: {repo}
**Dependencies**: {blocked_by_list or "None"}

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| {decision_1} | {rationale_1} |
| ... | ... |

## Files to Create/Modify

- `path/to/file1.py` - Description of changes
- `path/to/file2.py` - Description of changes

## Requirements

{foreach requirement in requirements}
### R{n}: {requirement.statement}

**Rationale**: {requirement.rationale}

**Acceptance Criteria**:
{foreach criterion in requirement.acceptance}
- [ ] {criterion}
{/foreach}

{/foreach}

## Verification

| ID | Title | Kind | Command | Blocking |
|----|-------|------|---------|----------|
{foreach v in verification}
| {v.id} | {v.title} | {v.kind} | `{v.command}` | {v.blocking} |
{/foreach}

## Definition of Done

- [ ] All acceptance criteria verified
- [ ] Verification commands pass
- [ ] Code reviewed and approved
- [ ] Documentation updated (if applicable)
- [ ] No regressions introduced
```

### Building Description

```python
def build_ticket_description(ticket_data: dict, args) -> str:
    """Build standardized ticket description."""
    lines = []

    # Summary
    lines.append("## Summary\n")
    if ticket_data.get("description"):
        lines.append(ticket_data["description"])
    else:
        lines.append(f"Implementation for: {ticket_data['title']}")
    lines.append("")

    # Metadata
    repo = args.repo or ticket_data.get("repo") or get_current_repo()
    lines.append(f"**Repository**: {repo}")

    blocked_by = [id.strip() for id in args.blocked_by.split(",") if id.strip()] if args.blocked_by else []
    deps = ", ".join(blocked_by) if blocked_by else "None"
    lines.append(f"**Dependencies**: {deps}")
    lines.append("")

    # Design Decisions (from context if available)
    lines.append("## Design Decisions\n")
    lines.append("| Decision | Rationale |")
    lines.append("|----------|-----------|")
    if ticket_data.get("context", {}).get("patterns_found"):
        for pattern in ticket_data["context"]["patterns_found"]:
            lines.append(f"| Follow {pattern} pattern | Consistency with codebase |")
    else:
        lines.append("| *To be determined during implementation* | |")
    lines.append("")

    # Files to Create/Modify
    lines.append("## Files to Create/Modify\n")
    if ticket_data.get("context", {}).get("relevant_files"):
        for f in ticket_data["context"]["relevant_files"]:
            lines.append(f"- `{f}`")
    else:
        lines.append("- *To be determined during implementation*")
    lines.append("")

    # Requirements
    lines.append("## Requirements\n")
    requirements = ticket_data.get("requirements", [])
    if requirements:
        for i, req in enumerate(requirements, 1):
            req_id = req.get("id", f"R{i}")
            lines.append(f"### {req_id}: {req.get('statement', 'TBD')}\n")
            if req.get("rationale"):
                lines.append(f"**Rationale**: {req['rationale']}\n")
            lines.append("**Acceptance Criteria**:")
            for criterion in req.get("acceptance", []):
                lines.append(f"- [ ] {criterion}")
            lines.append("")
    else:
        lines.append("*Requirements to be defined*\n")

    # Verification
    lines.append("## Verification\n")
    verification = ticket_data.get("verification", [])
    if verification:
        lines.append("| ID | Title | Kind | Command | Blocking |")
        lines.append("|----|-------|------|---------|----------|")
        for v in verification:
            cmd = f"`{v.get('command', 'N/A')}`"
            blocking = "Yes" if v.get("blocking", True) else "No"
            lines.append(f"| {v.get('id', '-')} | {v.get('title', '-')} | {v.get('kind', '-')} | {cmd} | {blocking} |")
    else:
        lines.append("*Default verification steps will be used*")
    lines.append("")

    # Definition of Done
    lines.append("## Definition of Done\n")
    lines.append("- [ ] All acceptance criteria verified")
    lines.append("- [ ] Verification commands pass")
    lines.append("- [ ] Code reviewed and approved")
    lines.append("- [ ] Documentation updated (if applicable)")
    lines.append("- [ ] No regressions introduced")

    return "\n".join(lines)
```

---

## Linear MCP Integration

### Creating Ticket

```
mcp__linear-server__create_issue(
    title="{ticket_title}",
    team="{team}",  # Default: Omninode
    description="{generated_description}",
    project="{project}",  # If --project provided
    parentId="{parent}",  # If --parent provided
    blockedBy=["{id1}", "{id2}"]  # If --blocked-by provided
)
```

### Updating Existing Ticket

```
mcp__linear-server__update_issue(
    id="{existing_ticket_id}",
    description="{merged_description}"
)
```

### Canceling Ticket

```
mcp__linear-server__update_issue(
    id="{existing_ticket_id}",
    state="Canceled"
)
```

---

## Execution Flow

### Step 1: Parse Arguments

```python
# Validate mutual exclusivity
sources = [args.title, args.from_contract, args.from_plan]
source_count = sum(1 for s in sources if s)

if source_count == 0:
    error("Must provide ticket source")
if source_count > 1:
    error("Arguments are mutually exclusive")

if args.from_plan and not args.milestone:
    error("--from-plan requires --milestone")
```

### Step 2: Load Ticket Data

```python
if args.title:
    ticket_data = {"title": args.title, ...}
elif args.from_contract:
    ticket_data = parse_contract_file(args.from_contract)
elif args.from_plan:
    ticket_data = parse_plan_milestone(args.from_plan, args.milestone)
```

### Step 3: Check for Conflicts

```python
existing = search_existing_tickets(ticket_data["title"], args.team)
if existing:
    resolution = ask_user_conflict_resolution(existing)
    if resolution == "update":
        update_existing_ticket(existing, ticket_data)
        return
    elif resolution == "cancel_create":
        cancel_ticket(existing["id"])
        # Continue to create new
    elif resolution == "skip":
        print(f"Skipped: {ticket_data['title']}")
        return
```

### Step 4: Generate Description

```python
description = build_ticket_description(ticket_data, args)
```

### Step 4.5: Validate Architecture Dependencies

When `--blocked-by` is provided, validate that dependencies respect the OmniNode architecture.

**Reference**: See `plugins/onex/lib/dependency_validator.md` for validation logic.

```python
# Import validation logic (conceptually - this is documentation)
from lib.dependency_validator import validate_dependencies, FOUNDATION_REPOS

if args.blocked_by:
    blocked_by_ids = [id.strip() for id in args.blocked_by.split(",") if id.strip()]
    ticket_repo = args.repo or get_current_repo()

    if not ticket_repo:
        print("Warning: No --repo specified and unable to detect repository. Skipping architecture validation.")
    else:
        violations = validate_dependencies(
            ticket_repo=ticket_repo,
            blocked_by_ids=blocked_by_ids,
            fetch_ticket_fn=lambda id: mcp__linear-server__get_issue(id=id)
        )

        # Filter warnings vs errors
        errors = [v for v in violations if not v.startswith("Warning:")]
        warnings = [v for v in violations if v.startswith("Warning:")]

        for w in warnings:
            print(w)

        if errors:
            if not args.allow_arch_violation:
                print("\nDependency architecture violations detected:\n")
                for err in errors:
                    print(f"  - {err}\n")
                print("\nValid dependencies flow: app→foundation or foundation→foundation.")
                print("To proceed anyway, use --allow-arch-violation flag.")
                raise SystemExit(1)
            else:
                print("\n[WARNING] Proceeding with architecture violations (--allow-arch-violation):\n")
                for err in errors:
                    print(f"  - {err}\n")
                # Append warning to description
                description += "\n\n---\n\n**Warning**: This ticket has dependencies that violate architecture guidelines."
```

**Architecture Rules**:
| Ticket Repo | Blocked By Repo | Verdict |
|-------------|-----------------|---------|
| application | application | INVALID (app→app) |
| foundation | application | INVALID (foundation→app) |
| application | foundation | VALID |
| foundation | foundation | VALID |

**Foundation repos**: omnibase_core, omnibase_spi, omnibase_infra

### Step 5: Create Ticket

```python
# Build create params
params = {
    "title": ticket_data["title"],
    "team": args.team or "Omninode",
    "description": description
}

if args.project:
    params["project"] = args.project
if args.parent:
    params["parentId"] = args.parent
if args.blocked_by:
    params["blockedBy"] = [id.strip() for id in args.blocked_by.split(",") if id.strip()]

result = mcp__linear-server__create_issue(**params)
```

### Step 6: Report Success

```python
print(f"""
Ticket created successfully!

  ID: {result["identifier"]}
  Title: {result["title"]}
  URL: {result["url"]}

  Team: {args.team or "Omninode"}
  Parent: {args.parent or "None"}
  Blocked by: {args.blocked_by or "None"}
""")
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| File not found | Report path, suggest checking location |
| YAML parse error | Show line number and syntax issue |
| Missing required field | Report which field is missing |
| Milestone not found | List available milestones in file |
| Architecture violation | List violations, suggest --allow-arch-violation to override |
| Linear API error | Report error, suggest checking permissions |
| Network timeout | Report timeout, suggest retry |

**Never:**
- Silently skip errors
- Create ticket with incomplete data
- Proceed without user confirmation on conflicts

---

## Examples

### Create from title
```
/create-ticket --title "Add rate limiting to API endpoints" --repo omnibase_core --team Omninode
```

### Create from contract file
```
/create-ticket --from-contract ./specs/rate-limiting.yaml --project "API Improvements"
```

### Create from plan milestone
```
/create-ticket --from-plan ./EVENT_ALIGNMENT_PLAN.md --milestone M4 --parent OMN-1800
```

### With dependencies
```
/create-ticket --title "Implement retry logic" --blocked-by OMN-1801,OMN-1802 --team Omninode
```

### Override architecture validation (rare)
```
/create-ticket --title "Cross-app coordination" --repo omniclaude --blocked-by OMN-1805 --allow-arch-violation
```
