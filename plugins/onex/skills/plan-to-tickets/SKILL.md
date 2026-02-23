---
name: plan-to-tickets
description: Batch create Linear tickets from a plan markdown file - parses phases/milestones, creates epic if needed, links dependencies
version: 1.0.0
category: workflow
tags: [linear, tickets, planning, batch]
author: OmniClaude Team
args:
  - name: plan-file
    description: Path to plan markdown file
    required: true
  - name: --project
    description: Linear project name
    required: false
  - name: --epic-title
    description: Title for epic (overrides auto-detection from plan)
    required: false
  - name: --no-create-epic
    description: Fail if epic doesn't exist (don't auto-create)
    required: false
  - name: --dry-run
    description: Show what would be created without creating
    required: false
  - name: --skip-existing
    description: Skip tickets that already exist (don't ask)
    required: false
  - name: --team
    description: Linear team name (default: Omninode)
    required: false
  - name: --repo
    description: Repository label for all tickets (e.g., omniclaude, omnibase_core)
    required: false
  - name: --allow-arch-violation
    description: Bypass architecture dependency validation
    required: false
---

# Batch Create Tickets from Plan

**Usage:** `/plan-to-tickets <plan-file> [options]`

**Arguments:**
- `plan-file` - Path to plan markdown file (required)
- `--project <name>` - Linear project name
- `--epic-title <title>` - Title for epic (overrides auto-detection from plan)
- `--no-create-epic` - Fail if epic doesn't exist (don't auto-create)
- `--dry-run` - Show what would be created without creating
- `--skip-existing` - Skip tickets that already exist (don't ask)
- `--team <name>` - Linear team name (default: Omninode)
- `--repo <label>` - Repository label for all tickets (e.g., omniclaude, omnibase_core)
- `--allow-arch-violation` - Bypass architecture dependency validation

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
    return plan_path.read_text(encoding='utf-8')
```

If file doesn't exist, report error and stop.

---

## Step 2: Detect Plan Structure

**Detection Cascade:**
1. If `## Phase N:` sections exist → use them (canonical)
2. Else if `## Milestones Overview` table with `**M#**` rows exists → fall back
3. Else if `**P0 —`/`**P1 —` priority labels exist → use them (priority_labels)
4. Else → fail fast with clear error listing all three formats

```python
import re

def detect_structure(content: str) -> tuple[str, list[dict]]:
    """Detect plan structure and extract entries.

    Returns:
        (structure_type, entries) where structure_type is one of:
          'phase_sections'  — ## Phase N: Title headings
          'milestone_table' — ## Milestones Overview with **M#** rows
          'priority_labels' — **P0 — title**: prose blocks
        entries is list of {id, title, content, dependencies}
    """
    # Try Phase sections first (canonical)
    # Requires 'Phase' keyword to avoid matching arbitrary numbered headings
    # Captures decimal phases: "## Phase 1.5: Title" -> phase_num = "1.5"
    phase_pattern = r'^## Phase\s+(\d+(?:\.\d+)?):\s*(.+?)$'
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

        # Check for duplicate phase IDs - fail fast to prevent wrong dependency linking
        seen_ids = {}
        for entry in entries:
            if entry['id'] in seen_ids:
                raise ValueError(
                    f"Duplicate phase ID '{entry['id']}' found. "
                    f"First: '{seen_ids[entry['id']]}', Second: '{entry['title']}'. "
                    f"Fix plan file to use unique phase numbers."
                )
            seen_ids[entry['id']] = entry['title']

        return ('phase_sections', entries)

    # Try Milestone table (legacy fallback)
    # Expected format: | **M1** | Deliverable | Dependencies |
    # Must have exactly 3 columns: ID, description, dependencies
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

    # Try priority labels (third fallback)
    # Matches bold P-prefixed labels used in ## Implementation Priority sections:
    #   **P0 — title**: description...
    #   **P0 — title** description...
    # The em-dash (—), en-dash (–), or hyphen (-) are all accepted.
    priority_pattern = r'^\*\*P(\d+)\s*[—\-–]\s*(.+?)(?:\*\*:|\*\*\s)'
    priority_matches = list(re.finditer(priority_pattern, content, re.MULTILINE))

    if not priority_matches:
        # Broader fallback: **P0 — anything** at start of line
        priority_pattern = r'^\*\*P(\d+)\s*[—\-–]\s*([^\n*]+?)(?:\*\*|$)'
        priority_matches = list(re.finditer(priority_pattern, content, re.MULTILINE))

    if priority_matches:
        entries = []
        for i, match in enumerate(priority_matches):
            p_num = match.group(1)
            title = match.group(2).strip().rstrip(':').strip()

            # Content: from start of label line to next P-label or ## heading
            label_start = match.start()
            content_start = match.end()
            if i + 1 < len(priority_matches):
                end = priority_matches[i + 1].start()
            else:
                next_h2 = re.search(r'^## ', content[content_start:], re.MULTILINE)
                end = content_start + next_h2.start() if next_h2 else len(content)

            # Include the label line for full context in the ticket description
            p_content = content[label_start:end].strip()
            deps = parse_dependencies(p_content)

            entries.append({
                'id': f'P{p_num}',
                'title': f'P{p_num}: {title}',
                'content': p_content,
                'dependencies': deps
            })

        # Check for duplicate IDs - fail fast
        seen_ids = {}
        for entry in entries:
            if entry['id'] in seen_ids:
                raise ValueError(
                    f"Duplicate priority ID '{entry['id']}' found. "
                    f"First: '{seen_ids[entry['id']]}', Second: '{entry['title']}'. "
                    f"Fix plan file to use unique priority numbers."
                )
            seen_ids[entry['id']] = entry['title']

        return ('priority_labels', entries)

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

        # P# -> P{N} (also handles P1_5 or P1.5 decimal variants)
        p_match = re.match(r'P(\d+(?:[._]\d+)?)', part, re.IGNORECASE)
        if p_match:
            # Normalize to underscore format for consistency
            phase_id = p_match.group(1).replace('.', '_')
            deps.append(f'P{phase_id}')
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
        limit=50
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
            for m in matches[:10]  # Limit to 10 for reasonable UI
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

    try:
        epic = mcp__linear-server__create_issue(**params)
        print(f"Created epic: {epic.get('identifier', 'unknown')} - {epic.get('title', epic_title)}")
        return epic
    except Exception as e:
        raise ValueError(f"Failed to create epic '{epic_title}': {e}")
```

---

## Step 5: Build Ticket Descriptions

```python
def build_ticket_description(entry: dict, structure_type: str, arch_violation_override: bool = False) -> str:
    """Build standardized ticket description from plan entry.

    Args:
        entry: Plan entry with title, content, dependencies
        structure_type: Type of plan structure (phase_sections or milestone_table)
        arch_violation_override: If True, add warning about architecture validation bypass
    """
    lines = []

    # Add architecture violation warning if applicable
    if arch_violation_override:
        lines.append("> **Architecture Override**: This ticket was created with `--allow-arch-violation` - cross-application dependency requires justification.\n")
        lines.append("")

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
        limit=50
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

## Step 7.5: Validate Architecture Dependencies

Before creating any tickets, validate that all external dependencies (OMN-#### references) respect the OmniNode architecture.

**Reference**: See `plugins/onex/lib/dependency_validator.md` for validation logic.

```python
# Validation runs before batch creation
from lib.dependency_validator import validate_dependencies, filter_errors, filter_warnings, FOUNDATION_REPOS

def validate_plan_dependencies(
    entries: list[dict],
    plan_repo: str | None,
    allow_override: bool,
    dry_run: bool
) -> tuple[bool, bool]:
    """Validate all external dependencies in the plan.

    Args:
        entries: List of plan entries with 'dependencies' field
        plan_repo: Repository label for all tickets in this plan
        allow_override: If True, warn but don't block
        dry_run: If True, just report what would be validated

    Returns:
        Tuple of (should_proceed, violations_overridden):
        - should_proceed: True if validation passes (or override set), False if should abort
        - violations_overridden: True if violations were found but overridden with --allow-arch-violation
    """
    if not plan_repo:
        print("Warning: No --repo specified. Skipping architecture validation.")
        print("  Provide --repo to enable dependency validation.")
        return (True, False)  # proceed, no violations overridden

    # Collect all external dependencies (OMN-#### format)
    external_deps = []
    for entry in entries:
        for dep in entry.get('dependencies', []):
            if dep.startswith('OMN-') and dep not in external_deps:
                external_deps.append(dep)

    if not external_deps:
        return (True, False)  # proceed, no violations overridden

    if dry_run:
        print(f"\n[DRY RUN] Would validate {len(external_deps)} external dependencies:")
        for dep in external_deps:
            print(f"  - {dep}")
        return (True, False)  # proceed, no violations overridden (can't know in dry run)

    # Validate each external dependency
    all_errors = []
    all_warnings = []

    for dep in external_deps:
        violations = validate_dependencies(
            ticket_repo=plan_repo,
            blocked_by_ids=[dep],
            fetch_ticket_fn=lambda id: mcp__linear-server__get_issue(id=id)
        )

        errors = filter_errors(violations)
        warnings = filter_warnings(violations)

        all_errors.extend(errors)
        all_warnings.extend(warnings)

    # Report warnings
    for w in all_warnings:
        print(f"[WARNING] {w.message}")

    # Handle errors
    if all_errors:
        print(f"\nArchitecture violations detected ({len(all_errors)}):\n")
        for err in all_errors:
            print(f"  - {err.message}\n")

        if allow_override:
            print("[WARNING] Proceeding with architecture violations (--allow-arch-violation)\n")
            return (True, True)  # proceed, violations WERE overridden
        else:
            print("Valid dependencies flow: app->foundation or foundation->foundation.")
            print("To proceed anyway, use --allow-arch-violation flag.")
            print("\nNo tickets created. Fix dependencies or use override flag.")
            return (False, False)  # abort, no override

    return (True, False)  # proceed, no violations to override


# Call before Step 8
plan_repo = args.repo  # May be None if not specified

should_proceed, arch_violation_override = validate_plan_dependencies(
    entries=entries,
    plan_repo=plan_repo,
    allow_override=args.allow_arch_violation,
    dry_run=args.dry_run
)

if not should_proceed:
    raise SystemExit(1)

# arch_violation_override is True if violations were found but --allow-arch-violation was used
# This flag will be passed to create_tickets_batch to annotate tickets with warnings
```

**Key behavior**:
- **Internal refs (P1, P2, M1)**: Not validated (same plan = same repo)
- **External refs (OMN-1234)**: Validated against architecture rules
- **No --repo**: Validation skipped with warning
- **--dry-run**: Shows what would be validated without API calls
- **Violations found**: Entire batch aborted (unless --allow-arch-violation)

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
    dry_run: bool,
    arch_violation_override: bool = False
) -> dict:
    """Create all tickets from plan entries.

    Args:
        entries: List of plan entries to create tickets for
        epic: Parent epic issue, or None
        team: Linear team name
        project: Linear project name, or None
        structure_type: Type of plan structure detected
        skip_existing: If True, skip existing tickets without asking
        dry_run: If True, don't actually create tickets
        arch_violation_override: If True, add warning annotation to ticket descriptions

    Returns:
        {created: [], skipped: [], updated: [], failed: [], id_map: {P1: OMN-xxx}}
    """
    import time  # For rate limiting between API calls

    # Linear has ~65KB description limit - define once for consistency
    MAX_DESC_SIZE = 60000  # Leave margin for safety

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
                    description = build_ticket_description(entry, structure_type, arch_violation_override)
                    existing_desc = existing.get('description', '') or ''
                    merged = f"{existing_desc}\n\n---\n\n## Updated from Plan\n\n{description}"

                    if len(merged) > MAX_DESC_SIZE:
                        merged = merged[:MAX_DESC_SIZE] + "\n\n[... truncated due to size limit]"

                    mcp__linear-server__update_issue(
                        id=existing['id'],
                        description=merged
                    )
                results['updated'].append({'entry': entry, 'existing': existing})
                results['id_map'][entry['id']] = existing['identifier']
                print(f"  Updated: {existing['identifier']}")
                continue

        # Create new ticket
        description = build_ticket_description(entry, structure_type, arch_violation_override)

        if len(description) > MAX_DESC_SIZE:
            description = description[:MAX_DESC_SIZE] + "\n\n[... truncated due to size limit]"

        # Resolve dependencies to actual ticket IDs (forward refs resolved in second pass)
        blocked_by = []
        unresolved_deps = []
        for dep in entry['dependencies']:
            if dep.startswith('OMN-'):
                blocked_by.append(dep)
            elif dep in results['id_map']:
                blocked_by.append(results['id_map'][dep])
            elif re.match(r'^P\d+(?:_\d+)?$', dep):
                # Forward reference (P# format) - will be resolved in second pass
                unresolved_deps.append(dep)
            else:
                # Unrecognized dependency format - warn user
                print(f"  Warning: Dependency '{dep}' has unrecognized format (expected OMN-###, P#, Phase #, or M#)")

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

        # Rate limiting: small delay between API calls to avoid hitting Linear rate limits
        time.sleep(0.2)  # 200ms delay = max 5 requests/second, well under Linear limits

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
            results['created'].append({
                'entry': entry,
                'ticket': result,
                'first_pass_blocked_by': blocked_by  # Store for merge in second pass
            })
            results['id_map'][entry['id']] = result['identifier']
            print(f"  Created: {result.get('identifier', 'unknown')} - {result.get('url', '(no URL)')}")

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
                # Merge with first-pass dependencies (Linear replaces, doesn't merge)
                # Only include first-pass deps that exist in id_map (validated IDs)
                first_pass = item.get('first_pass_blocked_by', [])
                id_map_values = set(results['id_map'].values())
                validated_first_pass = [
                    dep for dep in first_pass
                    if dep.startswith('OMN-') or dep in id_map_values
                ]
                all_blocked_by = validated_first_pass + new_blocked_by

                # Update ticket with combined dependencies
                mcp__linear-server__update_issue(
                    id=item['ticket']['id'],
                    blockedBy=all_blocked_by
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
        print(f"\nEpic: {epic.get('identifier', 'unknown')} - {epic.get('title', 'untitled')}")

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
                print(f"  - [{t.get('identifier', '?')}]({t.get('url', '#')}) - {t.get('title', '')[:50]}")

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
  1. Phase sections (canonical):
       ## Phase 1: Title
       ## Phase 2: Title
  2. Priority labels:
       **P0 — Title**: description...
       **P1 — Title**: description...
  3. Milestones table:
       ## Milestones Overview  (with **M1**, **M2** rows)

Example (phase sections):
  # My Plan
  ## Phase 1: Setup
  Description...
  ## Phase 2: Implementation
  Description...

Example (priority labels — no section headings needed):
  # My Plan
  **P0 — shared library**: Implement all helpers...
  **P1 — exception safety**: Wrap every acquire_claim()...

Provide a plan with one of the above structures.
""")
    # Stop execution
    raise SystemExit(1)

print(f"[structure_detected] type={structure_type} entries={len(entries)}")

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
    dry_run=args.dry_run,
    arch_violation_override=arch_violation_override  # Add warning to tickets if violations were overridden
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
| Architecture violation | Abort entire batch, list violations, suggest --allow-arch-violation |
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

# With repository label (enables architecture validation)
/plan-to-tickets ~/.claude/plans/my-plan.md --repo omniclaude --project "Workflow Automation"

# Override architecture validation for cross-app dependencies
/plan-to-tickets ~/.claude/plans/my-plan.md --repo omniclaude --allow-arch-violation
```
