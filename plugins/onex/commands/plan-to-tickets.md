---
name: plan-to-tickets
description: Batch create Linear tickets from a plan markdown file - parses phases/milestones, creates epic if needed, links dependencies
tags: [linear, tickets, planning, batch, automation]
args:
  - name: plan-file
    description: Path to plan markdown file
    required: true
  - name: project
    description: Linear project name
    required: false
  - name: epic-title
    description: Title for epic (overrides auto-detection from plan)
    required: false
  - name: no-create-epic
    description: Fail if epic doesn't exist (don't auto-create)
    required: false
  - name: dry-run
    description: Show what would be created without creating
    required: false
  - name: skip-existing
    description: Skip tickets that already exist (don't ask)
    required: false
  - name: team
    description: Linear team name (default Omninode)
    required: false
    default: "Omninode"
---

# Batch Create Tickets from Plan

Create Linear tickets from a plan markdown file. Parses phases or milestones, creates/links epic, resolves dependencies.

**Announce at start:** "Creating tickets from plan: {plan-file}"

---

## Step 1: Read and Validate Plan File

```python
from pathlib import Path

def read_plan_file(path: str) -> str:
    """Read plan file and validate it exists."""
    plan_path = Path(path).expanduser()
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {path}")
    return plan_path.read_text()
```

If file doesn't exist, report error and stop.

---

## Step 2: Detect Plan Structure

**Detection Cascade:**
1. If `## Phase` sections exist → use them (canonical)
2. Else if `## Milestones Overview` table exists → fall back
3. Else → fail fast with clear error

```python
import re

def detect_structure(content: str) -> tuple[str, list[dict]]:
    """Detect plan structure and extract entries.

    Returns:
        (structure_type, entries) where structure_type is 'phase_sections' or 'milestone_table'
        entries is list of {id, title, content, dependencies}
    """
    # Try Phase sections first (canonical)
    # Captures decimal phases: "## Phase 1.5: Title" -> phase_num = "1.5"
    phase_pattern = r'^## (?:Phase\s+)?(\d+(?:\.\d+)?):\s*(.+?)$'
    phase_matches = list(re.finditer(phase_pattern, content, re.MULTILINE | re.IGNORECASE))

    if phase_matches:
        entries = []
        for i, match in enumerate(phase_matches):
            phase_num = match.group(1)
            # Normalize: 1.5 -> 1_5 for valid ID
            phase_id = phase_num.replace('.', '_')
            title = match.group(2).strip()

            # Extract content until next ## heading or end
            start = match.end()
            if i + 1 < len(phase_matches):
                end = phase_matches[i + 1].start()
            else:
                # Find next ## heading or end of file
                next_h2 = re.search(r'^## ', content[start:], re.MULTILINE)
                end = start + next_h2.start() if next_h2 else len(content)

            phase_content = content[start:end].strip()

            # Parse dependencies from content (look for "Dependencies:" or "Depends on:")
            deps = parse_dependencies(phase_content)

            entries.append({
                'id': f'P{phase_id}',
                'title': f'Phase {phase_num}: {title}',
                'content': phase_content,
                'dependencies': deps
            })

        return ('phase_sections', entries)

    # Try Milestone table (legacy fallback)
    if '## Milestones Overview' in content or '## Milestone Overview' in content:
        # Find table rows with **M#** pattern
        table_pattern = r'\|\s*\*\*M(\d+)\*\*\s*\|([^|]+)\|([^|]*)\|'
        table_matches = re.findall(table_pattern, content)

        if table_matches:
            entries = []
            for m_num, deliverable, deps_str in table_matches:
                # Find corresponding ## Milestone N: section for content
                section_pattern = rf'^## (?:Milestone\s+)?{m_num}:\s*(.+?)$'
                section_match = re.search(section_pattern, content, re.MULTILINE | re.IGNORECASE)

                if section_match:
                    title = section_match.group(1).strip()
                    # Extract content
                    start = section_match.end()
                    next_h2 = re.search(r'^## ', content[start:], re.MULTILINE)
                    end = start + next_h2.start() if next_h2 else len(content)
                    m_content = content[start:end].strip()
                else:
                    title = deliverable.strip()
                    m_content = deliverable.strip()

                deps = parse_dependency_string(deps_str)

                entries.append({
                    'id': f'P{m_num}',  # Normalize to P# internally
                    'title': f'M{m_num}: {title}',
                    'content': m_content,
                    'dependencies': deps
                })

            return ('milestone_table', entries)

    # No valid structure found - fail fast
    return ('none', [])


def parse_dependencies(content: str) -> list[str]:
    """Extract dependencies from content block."""
    # Look for "Dependencies:", "Depends on:", "Blocked by:" lines
    dep_patterns = [
        r'(?:Dependencies|Depends on|Blocked by|Requires):\s*(.+?)(?:\n|$)',
        r'\*\*Dependencies?\*\*:\s*(.+?)(?:\n|$)',
    ]

    for pattern in dep_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return parse_dependency_string(match.group(1))

    return []


def parse_dependency_string(deps_str: str) -> list[str]:
    """Parse dependency string into normalized list.

    Supports: Phase 1, M1, Milestone 1, P1, OMN-1234, None
    Normalizes to: P1, P2, OMN-1234 format
    """
    if not deps_str or deps_str.strip().lower() in ('none', 'n/a', '-', ''):
        return []

    deps = []
    # Split on commas, "and", semicolons
    parts = re.split(r'[,;&]|\band\b', deps_str)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # OMN-#### ticket IDs - pass through
        omn_match = re.match(r'(OMN-\d+)', part, re.IGNORECASE)
        if omn_match:
            deps.append(omn_match.group(1).upper())
            continue

        # Phase N, Phase 1.5, etc -> P{N} or P{N.N}
        phase_match = re.match(r'Phase\s+(\d+(?:\.\d+)?)', part, re.IGNORECASE)
        if phase_match:
            # Normalize: P1.5 -> P1_5 for valid ID, or just use integer part
            phase_id = phase_match.group(1).replace('.', '_')
            deps.append(f'P{phase_id}')
            continue

        # M# or Milestone # -> P{N} (requires M prefix or "Milestone" word)
        m_match = re.match(r'(?:Milestone\s+|M)(\d+)', part, re.IGNORECASE)
        if m_match:
            deps.append(f'P{m_match.group(1)}')
            continue

        # P# -> P{N}
        p_match = re.match(r'P(\d+)', part, re.IGNORECASE)
        if p_match:
            deps.append(f'P{p_match.group(1)}')
            continue

    return deps
```

---

## Step 3: Extract Epic Title

```python
def extract_epic_title(content: str, override: str | None = None) -> str:
    """Extract epic title from plan or use override."""
    if override:
        return override

    # Find first # heading
    match = re.search(r'^# (.+?)$', content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    raise ValueError("No epic title found. Provide --epic-title or add a # heading to the plan.")
```

---

## Step 4: Resolve or Create Epic

```python
def resolve_epic(epic_title: str, team: str, no_create: bool, project: str | None, dry_run: bool = False) -> dict | None:
    """Find existing epic or create new one.

    Returns:
        Epic issue dict with 'id' and 'identifier', or None if --no-create-epic and not found
    """
    # Search for existing epic by title
    issues = mcp__linear-server__list_issues(
        query=epic_title,
        team=team,
        limit=10
    )

    # Filter for exact title matches (case-insensitive)
    matches = [
        i for i in issues.get('issues', [])
        if i.get('title', '').lower().strip() == epic_title.lower().strip()
    ]

    if len(matches) == 1:
        # Single match - auto-link
        epic = matches[0]
        print(f"Found existing epic: {epic['identifier']} - {epic['title']}")
        return epic

    if len(matches) > 1:
        # Multiple matches - ask user to disambiguate
        options = [
            {"label": f"{m['identifier']}: {m['title'][:40]}", "description": m.get('status', '')}
            for m in matches[:4]  # Limit to 4 for UI
        ]

        response = AskUserQuestion(
            questions=[{
                "question": f"Multiple epics match '{epic_title}'. Which one?",
                "header": "Epic",
                "options": options,
                "multiSelect": False
            }]
        )

        selected = response.get('answers', {}).get('Epic')
        if selected:
            # Parse identifier from selected label
            identifier = selected.split(':')[0]
            for m in matches:
                if m['identifier'] == identifier:
                    return m

        raise ValueError("No epic selected. Aborting.")

    # No matches - create new epic (unless --no-create-epic)
    if no_create:
        raise ValueError(f"No epic found matching '{epic_title}' and --no-create-epic was set.")

    if dry_run:
        print(f"[DRY RUN] Would create new epic: {epic_title}")
        return {'id': 'DRY-EPIC', 'identifier': 'DRY-EPIC', 'title': epic_title, '_dry_run': True}

    print(f"Creating new epic: {epic_title}")

    params = {
        "title": epic_title,
        "team": team,
        "description": f"Epic created from plan file.\n\n**Auto-generated by /plan-to-tickets**"
    }

    if project:
        params["project"] = project

    epic = mcp__linear-server__create_issue(**params)
    print(f"Created epic: {epic['identifier']} - {epic['title']}")
    return epic
```

---

## Step 5: Build Ticket Descriptions

```python
def build_ticket_description(entry: dict, epic_id: str | None, structure_type: str) -> str:
    """Build standardized ticket description from plan entry."""
    lines = []

    lines.append("## Summary\n")
    lines.append(entry['content'][:500] if entry['content'] else f"Implementation for: {entry['title']}")
    lines.append("")

    lines.append(f"**Source**: Plan file ({structure_type})")
    if entry['dependencies']:
        lines.append(f"**Dependencies**: {', '.join(entry['dependencies'])}")
    lines.append("")

    # Include full content if longer
    if len(entry['content']) > 500:
        lines.append("## Details\n")
        lines.append(entry['content'])
        lines.append("")

    lines.append("## Definition of Done\n")
    lines.append("- [ ] Requirements implemented")
    lines.append("- [ ] Tests added/updated")
    lines.append("- [ ] Code reviewed")
    lines.append("- [ ] Documentation updated (if applicable)")

    return "\n".join(lines)
```

---

## Step 6: Check for Existing Tickets

```python
def check_existing_ticket(title: str, team: str) -> dict | None:
    """Check if ticket with same title already exists."""
    issues = mcp__linear-server__list_issues(
        query=title,
        team=team,
        limit=5
    )

    for issue in issues.get('issues', []):
        if issue.get('title', '').lower().strip() == title.lower().strip():
            return issue

    return None
```

---

## Step 7: Handle Conflicts

```python
def handle_conflict(existing: dict, entry: dict, skip_existing: bool) -> str:
    """Handle ticket conflict. Returns action: 'update', 'skip', 'create_new', or 'abort'."""

    if skip_existing:
        return 'skip'

    response = AskUserQuestion(
        questions=[{
            "question": f"Ticket '{existing['identifier']}' already exists with title '{existing['title'][:40]}...'. How to proceed?",
            "header": "Conflict",
            "options": [
                {"label": "Skip", "description": "Don't create this ticket"},
                {"label": "Update existing", "description": "Merge description into existing ticket"},
                {"label": "Create new", "description": "Create duplicate with new ID"}
            ],
            "multiSelect": False
        }]
    )

    answer = response.get('answers', {}).get('Conflict', 'Skip')

    if 'Skip' in answer:
        return 'skip'
    elif 'Update' in answer:
        return 'update'
    elif 'Create' in answer:
        return 'create_new'

    return 'skip'
```

---

## Step 8: Create Tickets in Batch

```python
def create_tickets_batch(
    entries: list[dict],
    epic: dict | None,
    team: str,
    project: str | None,
    structure_type: str,
    skip_existing: bool,
    dry_run: bool
) -> dict:
    """Create all tickets from plan entries.

    Returns:
        {created: [], skipped: [], updated: [], failed: [], id_map: {P1: OMN-xxx}}
    """
    results = {
        'created': [],
        'skipped': [],
        'updated': [],
        'failed': [],
        'id_map': {}  # Maps P1 -> OMN-1234 for dependency resolution
    }

    for entry in entries:
        print(f"\nProcessing: {entry['title']}")

        # Check for existing
        existing = check_existing_ticket(entry['title'], team)

        if existing:
            action = handle_conflict(existing, entry, skip_existing)

            if action == 'skip':
                results['skipped'].append({'entry': entry, 'existing': existing})
                results['id_map'][entry['id']] = existing['identifier']
                print(f"  Skipped (exists): {existing['identifier']}")
                continue

            if action == 'update':
                if not dry_run:
                    description = build_ticket_description(entry, epic['id'] if epic else None, structure_type)
                    merged = f"{existing.get('description', '')}\n\n---\n\n## Updated from Plan\n\n{description}"
                    mcp__linear-server__update_issue(
                        id=existing['id'],
                        description=merged
                    )
                results['updated'].append({'entry': entry, 'existing': existing})
                results['id_map'][entry['id']] = existing['identifier']
                print(f"  Updated: {existing['identifier']}")
                continue

        # Create new ticket
        description = build_ticket_description(entry, epic['id'] if epic else None, structure_type)

        # Resolve dependencies to actual ticket IDs (forward refs resolved in second pass)
        blocked_by = []
        unresolved_deps = []
        for dep in entry['dependencies']:
            if dep.startswith('OMN-'):
                blocked_by.append(dep)
            elif dep in results['id_map']:
                blocked_by.append(results['id_map'][dep])
            else:
                # Forward reference - will be resolved in second pass
                unresolved_deps.append(dep)

        if unresolved_deps:
            # Store for second pass resolution
            entry['_unresolved_deps'] = unresolved_deps

        if dry_run:
            print(f"  [DRY RUN] Would create: {entry['title']}")
            if blocked_by:
                print(f"    Dependencies: {blocked_by}")
            results['created'].append({'entry': entry, 'dry_run': True})
            results['id_map'][entry['id']] = f"DRY-{entry['id']}"
            continue

        try:
            params = {
                "title": entry['title'],
                "team": team,
                "description": description
            }

            if project:
                params["project"] = project

            if epic:
                params["parentId"] = epic['id']

            if blocked_by:
                params["blockedBy"] = blocked_by

            result = mcp__linear-server__create_issue(**params)
            results['created'].append({'entry': entry, 'ticket': result})
            results['id_map'][entry['id']] = result['identifier']
            print(f"  Created: {result['identifier']} - {result['url']}")

        except Exception as e:
            results['failed'].append({'entry': entry, 'error': str(e)})
            print(f"  Failed: {e}")

    # Second pass: resolve forward dependencies
    for item in results['created']:
        if item.get('dry_run'):
            continue

        entry = item['entry']
        unresolved = entry.get('_unresolved_deps', [])
        if not unresolved:
            continue

        # Resolve forward references now that all tickets exist
        new_blocked_by = []
        for dep in unresolved:
            if dep in results['id_map']:
                new_blocked_by.append(results['id_map'][dep])
            else:
                print(f"  Warning: Unresolved dependency '{dep}' for {item['ticket']['identifier']}")

        if new_blocked_by and not dry_run:
            try:
                # Update ticket with forward dependencies
                mcp__linear-server__update_issue(
                    id=item['ticket']['id'],
                    blockedBy=new_blocked_by
                )
                print(f"  Linked forward deps for {item['ticket']['identifier']}: {new_blocked_by}")
            except Exception as e:
                print(f"  Warning: Failed to link forward deps for {item['ticket']['identifier']}: {e}")

    return results
```

---

## Step 9: Report Summary

```python
def report_summary(results: dict, epic: dict | None, structure_type: str, dry_run: bool):
    """Print final summary."""

    mode = "[DRY RUN] " if dry_run else ""

    print(f"\n{'='*60}")
    print(f"{mode}Plan to Tickets Summary")
    print(f"{'='*60}")

    if epic:
        print(f"\nEpic: {epic['identifier']} - {epic['title']}")

    print(f"Structure detected: {structure_type}")
    print(f"\nResults:")
    print(f"  Created: {len(results['created'])}")
    print(f"  Skipped: {len(results['skipped'])}")
    print(f"  Updated: {len(results['updated'])}")
    print(f"  Failed:  {len(results['failed'])}")

    if results['created']:
        print(f"\n### Created Tickets")
        for item in results['created']:
            if item.get('dry_run'):
                print(f"  - [DRY] {item['entry']['title']}")
            else:
                t = item['ticket']
                print(f"  - [{t['identifier']}]({t['url']}) - {t['title'][:50]}")

    if results['skipped']:
        print(f"\n### Skipped (already exist)")
        for item in results['skipped']:
            e = item['existing']
            print(f"  - {e['identifier']} - {e['title'][:50]}")

    if results['failed']:
        print(f"\n### Failed")
        for item in results['failed']:
            print(f"  - {item['entry']['title']}: {item['error']}")
```

---

## Main Execution Flow

```python
# Step 1: Read plan file
content = read_plan_file(args.plan_file)

# Step 2: Detect structure
structure_type, entries = detect_structure(content)

if structure_type == 'none' or not entries:
    # Fail fast with clear error
    print(f"""
Error: No valid plan structure found in {args.plan_file}

Expected one of:
  1. Phase sections: ## Phase 1: Title, ## Phase 2: Title, ...
  2. Milestones table: ## Milestones Overview with **M1**, **M2** rows

Example (Phase sections):
  # My Plan
  ## Phase 1: Setup
  Description...
  ## Phase 2: Implementation
  Description...

Provide a plan with explicit phases or milestones.
""")
    # Stop execution
    raise SystemExit(1)

print(f"Detected structure: {structure_type}")
print(f"Found {len(entries)} entries to process")

# Step 3: Extract epic title
epic_title = extract_epic_title(content, args.epic_title)
print(f"Epic title: {epic_title}")

# Step 4: Resolve or create epic (even in dry-run mode for preview)
epic = None
try:
    epic = resolve_epic(epic_title, args.team, args.no_create_epic, args.project, dry_run=args.dry_run)
except ValueError as e:
    print(f"Error: {e}")
    raise SystemExit(1)

# Step 5-8: Create tickets
results = create_tickets_batch(
    entries=entries,
    epic=epic,
    team=args.team,
    project=args.project,
    structure_type=structure_type,
    skip_existing=args.skip_existing,
    dry_run=args.dry_run
)

# Step 9: Report summary
report_summary(results, epic, structure_type, args.dry_run)
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Plan file not found | Report path, stop |
| No valid structure | Fail fast with example |
| Epic not found + --no-create-epic | Report and stop |
| Multiple epic matches | AskUserQuestion to disambiguate |
| Ticket creation fails | Log error, continue with remaining |
| Dependency not resolved | Log warning, skip dependency link (forward refs resolved in second pass) |

---

## Examples

```bash
# Basic usage - detect structure, create epic, create tickets
/plan-to-tickets ~/.claude/plans/velvety-fluttering-sonnet.md

# With project assignment
/plan-to-tickets ~/.claude/plans/my-plan.md --project "Workflow Automation"

# Preview without creating
/plan-to-tickets ~/.claude/plans/my-plan.md --dry-run

# Auto-skip existing tickets
/plan-to-tickets ~/.claude/plans/my-plan.md --skip-existing

# Use specific epic title
/plan-to-tickets ~/.claude/plans/my-plan.md --epic-title "My Epic Title"

# Fail if epic doesn't exist
/plan-to-tickets ~/.claude/plans/my-plan.md --no-create-epic --epic-title "Existing Epic"
```
