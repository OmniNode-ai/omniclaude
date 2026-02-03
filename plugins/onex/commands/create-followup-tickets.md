---
name: create-followup-tickets
description: Create Linear tickets from code review issues found in the current session
tags: [linear, tickets, review, batch]
args:
  - name: project
    description: Linear project name (supports partial/fuzzy matching)
    required: true
  - name: from-file
    description: Path to review file (optional fallback, uses session context by default)
    required: false
  - name: repo
    description: Repository label override (auto-detected by default)
    required: false
  - name: no-repo-label
    description: Skip adding repository label
    required: false
  - name: parent
    description: Parent issue ID for all created tickets (e.g., OMN-1850)
    required: false
  - name: include-nits
    description: Include nitpick-level issues
    required: false
  - name: only-critical
    description: Only create tickets for critical issues
    required: false
  - name: only-major
    description: Only create tickets for critical and major issues
    required: false
  - name: dry-run
    description: Preview tickets without creating them
    required: false
  - name: auto
    description: Skip confirmation and create all tickets
    required: false
  - name: team
    description: Linear team name (default Omninode)
    required: false
    default: "Omninode"
---

# Create Follow-up Tickets from Code Review

Create Linear tickets from unresolved code review issues. Uses the current session's review output (from `/local-review` or `/pr-review-dev`) as the source.

**Announce at start:** "Creating follow-up tickets from code review for project '{project}'."

---

## Workflow

1. **Find review data** - Look for review output in session context
2. **Resolve project** - Fuzzy match project name via Linear API
3. **Detect repo label** - Auto-detect from git remote
4. **Filter issues** - Apply severity filters
5. **Preview tickets** - Show what will be created
6. **Create tickets** - Batch create with conflict detection

---

## Step 1: Find Review Data

### From Session Context (Default)

Look backward in the conversation for review output. The review JSON has this structure:

```json
{
  "critical": [{"file": "path", "line": 123, "description": "issue", "keyword": "trigger"}],
  "major": [...],
  "minor": [...],
  "nit": [...]
}
```

**Search patterns** in session:
- JSON blocks with `critical`, `major`, `minor`, `nit` arrays
- Markdown sections with "Critical Issues", "Major Issues" headings
- Output from `pr-quick-review`, `local-review`, `collate-issues`

If no review data found in session:
```
No review data found in current session.

Run one of these first:
  /local-review          # Review local changes
  /pr-review-dev <PR#>   # Review a PR

Or provide a file:
  /create-followup-tickets "project" --from-file ./tmp/pr-review-78.md
```

### From File (Fallback)

If `--from-file` provided, read and parse the review file:

```python
def parse_review_file(path: str) -> dict:
    """Parse review file (JSON or Markdown)."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Review file not found: {path}")
    content = file_path.read_text()

    # Try JSON first
    if path.endswith('.json'):
        return json.loads(content)

    # Parse Markdown format
    issues = {"critical": [], "major": [], "minor": [], "nit": []}
    current_severity = None

    for line in content.split('\n'):
        # Check for issue lines first (before severity detection)
        # This prevents issues with descriptions like "critical bug" from being misclassified
        if line.startswith('- **') and current_severity:
            # Parse: - **file:line** - description [`keyword`]
            # Extract: {"file": str, "line": int, "description": str, "keyword": str}
            issue = parse_issue_line(line)
            if issue:
                issues[current_severity].append(issue)
        else:
            # Check for severity headers (only markdown headers, not arbitrary text)
            # This prevents commentary like "major refactoring" from changing severity
            stripped = line.strip()
            if stripped.startswith('#'):
                line_lower = stripped.lower()
                if 'critical' in line_lower:
                    current_severity = 'critical'
                elif 'major' in line_lower:
                    current_severity = 'major'
                elif 'minor' in line_lower:
                    current_severity = 'minor'
                elif 'nit' in line_lower:
                    current_severity = 'nit'

    return issues


def parse_issue_line(line: str) -> dict | None:
    """Parse a single issue line from markdown format.

    Input format: - **file:line** - description [`keyword`]
    Returns: {"file": str, "line": int, "description": str, "keyword": str}
    """
    import re

    # Pattern: - **file:line** - description [`keyword`]
    pattern = r'^- \*\*([^:]+):(\d+)\*\* - (.+?)(?:\s*\[`([^`]+)`\])?$'
    match = re.match(pattern, line.strip())

    if not match:
        return None

    return {
        "file": match.group(1),
        "line": int(match.group(2)),
        "description": match.group(3).strip(),
        "keyword": match.group(4) or "unspecified"
    }
```

---

## Step 2: Resolve Project (Fuzzy Matching)

```python
# Fetch all projects (use high limit to avoid missing projects in large orgs)
projects = mcp__linear-server__list_projects(limit=200)

# Fuzzy match
query = args.project.lower()
matches = [p for p in projects if query in p['name'].lower()]

# Warn if we hit the limit (may be missing projects)
if len(projects) >= 200:
    print(f"Note: {len(projects)} projects found. If your project isn't listed, try a more specific name.")

if len(matches) == 0:
    # List available projects and let user select
    print("No matching projects found. Available projects:")
    project_options = projects[:4]  # Limit to 4 for AskUserQuestion
    for p in project_options:
        print(f"  - {p['name']}")

    response = AskUserQuestion(
        questions=[{
            "question": "Select a project from the list:",
            "header": "Project",
            "options": [{"label": p['name'], "description": p.get('description', '')[:50]} for p in project_options],
            "multiSelect": False
        }]
    )
    # User selects from options; response contains selected label
    selected_name = response['answers']['Project']
    project = next((p for p in projects if p['name'] == selected_name), None)
    if not project:
        raise ValueError(f"Project not found: {selected_name}")

elif len(matches) == 1:
    project = matches[0]
    print(f"Using project: {project['name']}")

else:
    # Multiple matches - ask user to select
    response = AskUserQuestion(
        questions=[{
            "question": f"Multiple projects match '{args.project}'. Which one?",
            "header": "Project",
            "options": [{"label": p['name'], "description": p.get('description', '')[:50]} for p in matches[:4]],
            "multiSelect": False
        }]
    )
    # User selects from options; response contains selected label
    selected_name = response['answers']['Project']
    project = next((p for p in matches if p['name'] == selected_name), None)
    if not project:
        raise ValueError(f"Project not found: {selected_name}")

# Extract project_id for ticket creation
project_id = project['id']
print(f"Project ID: {project_id}")
```

---

## Step 3: Detect Repository Label

```python
def detect_repo_label(args) -> str | None:
    """Auto-detect repository label from git remote or use override."""
    if args.no_repo_label:
        return None

    if args.repo:
        return args.repo

    # Auto-detect from git
    import subprocess
    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            capture_output=True, text=True, check=True
        )
        # Extract repo name from URL (e.g., git@github.com:org/omniclaude.git -> omniclaude)
        url = result.stdout.strip()
        repo_name = url.rstrip('.git').split('/')[-1]
    except subprocess.CalledProcessError:
        # Fallback to directory name
        repo_name = Path.cwd().name

    # Map repo name to Linear label (most repos use same name)
    label_mapping = {
        'omniclaude': 'omniclaude',
        'omnibase_core': 'omnibase_core',
        'omnibase_infra': 'omnibase_infra',
        'omniarchon': 'omniarchon',
        'omnidash': 'omnidash',
    }

    return label_mapping.get(repo_name, repo_name)

# Call this in workflow and store result
repo_label = detect_repo_label(args)
```

**Label mapping**:
| Repo | Linear Label |
|------|--------------|
| omniclaude | `omniclaude` |
| omnibase_core | `omnibase_core` |
| omnibase_infra | `omnibase_infra` |
| omniarchon | `omniarchon` |
| omnidash | `omnidash` |

If `--no-repo-label` is set, skip this step.
If `--repo <label>` is set, use that instead of auto-detection.

---

## Step 4: Filter Issues

```python
def filter_issues(review_data: dict, args) -> list:
    """Filter issues based on severity args."""
    issues = []

    # Determine which severities to include
    if args.only_critical:
        severities = ['critical']
    elif args.only_major:
        severities = ['critical', 'major']
    elif args.include_nits:
        severities = ['critical', 'major', 'minor', 'nit']
    else:
        # Default: critical, major, minor (no nits)
        severities = ['critical', 'major', 'minor']

    # Collect issues
    for severity in severities:
        for issue in review_data.get(severity, []):
            issues.append({
                **issue,
                'severity': severity
            })

    return issues
```

---

## Step 5: Preview Tickets

Display what will be created:

```markdown
## Tickets to Create ({count})

**Project**: {project_name}
**Labels**: {repo_label}, from-review
**Parent**: {parent_id or "None"}

### Critical ({count})
1. `[CRITICAL] {description[:50]}...` ({file}:{line})

### Major ({count})
2. `[MAJOR] {description[:50]}...` ({file}:{line})
3. `[MAJOR] {description[:50]}...` ({file}:{line})

### Minor ({count})
4. `[MINOR] {description[:50]}...` ({file}:{line})

---

**Mode**: {dry-run | auto | confirm}
```

If `--dry-run`: Stop here, don't create tickets.
If `--auto`: Proceed without confirmation.
Otherwise: Ask for confirmation via AskUserQuestion.

---

## Step 6: Create Tickets

For each issue, create a Linear ticket:

```python
def create_ticket(issue: dict, project_id: str, repo_label: str | None, args) -> dict:
    """Create a single Linear ticket from review issue."""

    # Build title
    severity_upper = issue['severity'].upper()
    file_ref = f" ({issue['file']}:{issue.get('line', '?')})" if issue.get('file') else ""
    title = f"[{severity_upper}] {issue['description'][:60]}{file_ref}"

    # Build description
    description = f"""## Review Issue

**Severity**: {severity_upper}
**Keyword**: `{issue.get('keyword', 'N/A')}`
**Source**: Code review follow-up

## Details

{issue['description']}

## Location

- **File**: `{issue.get('file', 'N/A')}`
- **Line**: {issue.get('line', 'N/A')}

## Definition of Done

- [ ] Issue addressed in code
- [ ] Tests added/updated if applicable
- [ ] PR created and reviewed
"""

    # Map severity to priority
    priority_map = {
        'critical': 1,  # Urgent
        'major': 2,     # High
        'minor': 3,     # Normal
        'nit': 4        # Low
    }

    # Build labels (repo_label comes from detect_repo_label())
    labels = [issue['severity'], 'from-review']
    if repo_label:
        labels.append(repo_label)

    # Create ticket
    params = {
        "title": title,
        "description": description,
        "team": args.team or "Omninode",
        "project": project_id,
        "priority": priority_map.get(issue['severity'], 3),
        "labels": labels
    }

    if args.parent:
        params["parentId"] = args.parent

    return mcp__linear-server__create_issue(**params)
```

### Batch Creation Loop

```python
created = []
failed = []

for i, issue in enumerate(issues, 1):
    print(f"Creating ticket {i}/{len(issues)}: [{issue['severity'].upper()}] {issue['description'][:40]}...")

    try:
        result = create_ticket(issue, project_id, repo_label, args)
        created.append(result)
        print(f"  Created: {result['identifier']} - {result['url']}")
    except Exception as e:
        failed.append({'issue': issue, 'error': str(e)})
        print(f"  Failed: {e}")

# Summary
print(f"\n## Summary\n")
print(f"Created: {len(created)} tickets")
print(f"Failed: {len(failed)} tickets")

if created:
    print(f"\n### Created Tickets\n")
    for t in created:
        print(f"- [{t['identifier']}]({t['url']}) - {t['title'][:50]}")
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| No review data in session | Suggest running review first or using --from-file |
| No matching project | List available projects |
| Multiple project matches | Ask user to select |
| Ticket creation fails | Log error, continue with remaining issues |
| Invalid --from-file path | Report path not found |

---

## Examples

```bash
# Basic usage after /local-review
/create-followup-tickets "beta hardening"

# Only critical issues, auto-create
/create-followup-tickets "beta hardening" --only-critical --auto

# Preview without creating
/create-followup-tickets "beta hardening" --dry-run

# Include nits, link to parent
/create-followup-tickets "beta hardening" --include-nits --parent OMN-1850

# Override repo label
/create-followup-tickets "beta hardening" --repo omnibase_core

# From explicit file
/create-followup-tickets "beta hardening" --from-file ./tmp/pr-review-78.md
```
