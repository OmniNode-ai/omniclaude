# Create Follow-up Tickets -- Poly Worker Prompt

You are creating Linear tickets from unresolved code review issues. Uses the current session's review output (from `/local-review` or `/pr-release-ready`) or an explicit review file as the source.

## Arguments

- `PROJECT` (string): Linear project name (required, supports partial/fuzzy matching)
- `FROM_FILE` (string): Path to review file (optional, uses session context by default)
- `REPO` (string): Repository label override (auto-detected by default)
- `NO_REPO_LABEL` (bool): Skip adding repository label
- `PARENT` (string): Parent issue ID for all created tickets (e.g., OMN-1850)
- `INCLUDE_NITS` (bool): Include nitpick-level issues
- `ONLY_CRITICAL` (bool): Only create tickets for critical issues
- `ONLY_MAJOR` (bool): Only create tickets for critical and major issues
- `DRY_RUN` (bool): Preview tickets without creating them
- `AUTO` (bool): Skip confirmation and create all tickets
- `TEAM` (string): Linear team name (default: Omninode)

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
- Output from `local-review`, `pr-release-ready`, `collate-issues`

If no review data found in session:
```
No review data found in current session.

Run one of these first:
  /local-review             # Review local changes
  /pr-release-ready <PR#>   # Review a PR

Or provide a file:
  /create-followup-tickets "project" --from-file ./tmp/pr-review-78.md
```

### From File (Fallback)

If `FROM_FILE` provided, read and parse the review file:

```python
def parse_review_file(path: str) -> dict:
    """Parse review file (JSON or Markdown)."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Review file not found: {path}")
    content = file_path.read_text()

    # Try JSON first
    if path.endswith('.json'):
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in review file {path}: {e}")

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
    # Line number is optional to handle issues without specific line references
    # Uses non-greedy match with backtracking to handle paths with colons (e.g., C:\path)
    pattern = r'^- \*\*(.+?)(?::(\d+))?\*\* - (.+?)(?:\s*\[`([^`]+)`\])?$'
    match = re.match(pattern, line.strip())

    if not match:
        return None

    line_num = match.group(2)
    return {
        "file": match.group(1),
        "line": int(line_num) if line_num else None,
        "description": match.group(3).strip(),
        "keyword": match.group(4) or "unspecified"
    }
```

---

## Step 2: Resolve Project (Fuzzy Matching)

```python
# Fetch all projects (use high limit to avoid missing projects in large orgs)
projects = mcp__linear-server__list_projects(limit=200)

# Validate API response (may return list or dict with 'projects' key)
if isinstance(projects, dict):
    projects = projects.get('projects', projects.get('nodes', []))
if not isinstance(projects, list):
    raise ValueError(f"Unexpected response from Linear API: {type(projects).__name__}")

# Handle empty workspace
if len(projects) == 0:
    raise ValueError("No projects found in Linear workspace. Please create a project first.")

# Substring match (case-insensitive, with defensive access)
query = args.project.lower()
matches = [p for p in projects if query in p.get('name', '').lower()]

# Warn if we hit the limit (may be missing projects)
if len(projects) >= 200:
    print(f"Note: {len(projects)} projects found. If your project isn't listed, try a more specific name.")

if len(matches) == 0:
    # No projects match query - list available and let user select
    project_options = projects[:4]  # Limit to 4 for AskUserQuestion
    print(f"No projects match '{query}'. Showing {len(project_options)} of {len(projects)} available projects:")
    for p in project_options:
        print(f"  - {p.get('name', 'Unnamed')}")

    response = AskUserQuestion(
        questions=[{
            "question": "Select a project from the list:",
            "header": "Project",
            "options": [{"label": p.get('name', 'Unnamed'), "description": (p.get('description') or '')[:50]} for p in project_options],
            "multiSelect": False
        }]
    )
    selected_name = response.get('answers', {}).get('Project')
    if not selected_name:
        raise ValueError("No project selected from options")
    project = next((p for p in projects if p.get('name') == selected_name), None)
    if not project:
        raise ValueError(f"Project not found: {selected_name}")

elif len(matches) == 1:
    project = matches[0]
    print(f"Using project: {project.get('name', 'Unnamed')}")

else:
    # Multiple matches - ask user to select
    display_matches = matches[:4]  # UI limit
    if len(matches) > 4:
        print(f"Showing 4 of {len(matches)} matches. Use a more specific query to narrow results.")
    response = AskUserQuestion(
        questions=[{
            "question": f"Multiple projects match '{args.project}'. Which one?",
            "header": "Project",
            "options": [{"label": p.get('name', 'Unnamed'), "description": (p.get('description') or '')[:50]} for p in display_matches],
            "multiSelect": False
        }]
    )
    selected_name = response.get('answers', {}).get('Project')
    if not selected_name:
        raise ValueError("No project selected from options")
    project = next((p for p in matches if p.get('name') == selected_name), None)
    if not project:
        raise ValueError(f"Project not found: {selected_name}")

# Extract project_id for ticket creation (validate required field)
project_id = project.get('id')
if not project_id:
    raise ValueError(f"Project '{project.get('name', 'Unnamed')}' is missing required 'id' field")
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
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # Fallback to directory name (handles: git not installed, no remote, permission errors)
        repo_name = Path.cwd().name

    # Map repo name to Linear label (most repos use same name)
    label_mapping = {
        'omniclaude': 'omniclaude',
        'omnibase_core': 'omnibase_core',
        'omnibase_infra': 'omnibase_infra',
        'omniarchon': 'omniarchon',
        'omnidash': 'omnidash',
    }

    # Only use known labels to prevent label pollution from unexpected repo names
    return label_mapping.get(repo_name)

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

If `NO_REPO_LABEL` is set, skip this step.
If `REPO` is set, use that instead of auto-detection.

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

    # Collect issues (use 'or []' to handle None values, not just missing keys)
    for severity in severities:
        for issue in review_data.get(severity) or []:
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

If `DRY_RUN`: Stop here, don't create tickets.
If `AUTO`: Proceed without confirmation.
Otherwise: Ask for confirmation via AskUserQuestion.

---

## Step 6: Create Tickets

For each issue, create a Linear ticket:

```python
def create_ticket(issue: dict, project_id: str, repo_label: str | None, args) -> dict:
    """Create a single Linear ticket from review issue."""

    # Build title
    severity_upper = issue['severity'].upper()
    # Use 'or' to handle both missing key AND None value (since line can be None)
    line_ref = issue.get('line') or '?'
    file_ref = f" ({issue['file']}:{line_ref})" if issue.get('file') else ""
    title = f"[{severity_upper}] {issue['description'][:60]}{file_ref}"

    # Build description
    description = f"""## Review Issue

**Severity**: {severity_upper}
**Keyword**: `{issue.get('keyword', 'N/A')}`
**Source**: Code review follow-up

## Details

{issue['description']}

## Location

- **File**: `{issue.get('file') or 'N/A'}`
- **Line**: {issue.get('line') or 'N/A'}

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
        # Use defensive access for API response fields
        identifier = result.get('identifier', 'unknown')
        url = result.get('url', 'N/A')
        print(f"  Created: {identifier} - {url}")
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
        # Use defensive access for API response fields
        identifier = t.get('identifier', 'unknown')
        url = t.get('url', '#')
        title = t.get('title', 'Untitled')[:50]
        print(f"- [{identifier}]({url}) - {title}")
```

---

## Architecture Validation

**Note**: This command does not support `--blocked-by` dependencies between tickets. Each follow-up ticket is created independently from review issues.

The `--parent` flag creates a parent-child relationship (epic grouping), NOT a blocking dependency, so architecture validation does not apply.

If dependency support is added in the future, integrate validation using `plugins/onex/lib/dependency_validator.md`.

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
