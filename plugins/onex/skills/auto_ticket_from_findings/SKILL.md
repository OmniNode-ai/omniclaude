---
description: Auto-create Linear tickets from sweep/review findings with deduplication against existing tickets
mode: full
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags:
  - linear
  - tickets
  - automation
  - sweep
  - dedup
  - contract-sweep
  - dod-sweep
  - hostile-review
author: OmniClaude Team
composable: true
args:
  - name: --findings
    description: "JSON string or file path containing structured findings"
    required: false
  - name: --source
    description: "Source label: contract-sweep | dod-sweep | hostile-review (auto-detected if omitted)"
    required: false
  - name: --parent
    description: "Parent issue ID for epic relationship (e.g., OMN-1800)"
    required: false
  - name: --project
    description: "Linear project name"
    required: false
  - name: --team
    description: "Linear team name (default: Omninode)"
    required: false
  - name: --dry-run
    description: "Preview tickets without creating them"
    required: false
  - name: --severity-threshold
    description: "Minimum severity for ticket creation: critical | major | minor | nit (default: minor)"
    required: false
  - name: --repo
    description: "Repository label override (e.g., omniclaude, omnibase_core)"
    required: false
---

# Auto-Ticket from Findings

Automatically create Linear tickets from structured findings produced by sweep and review
skills. Deduplicates against existing Linear tickets to prevent duplicates.

## When to Use

Use this skill as the downstream action after any sweep or review that produces structured
findings:

- After `/contract-sweep` completes with findings
- After `/dod-sweep` identifies compliance gaps
- After `/hostile-reviewer` produces issue reports
- After `/local-review` or `/pr-review-dev` with follow-up work

This skill is **composable** -- sweep skills can invoke it directly to create tickets
for their findings without manual intervention.

## Usage

```bash
# From session context (findings in current conversation)
/auto-ticket-from-findings --source contract-sweep

# From file
/auto-ticket-from-findings --findings ./tmp/sweep-findings.json --source dod-sweep

# Dry run (preview only)
/auto-ticket-from-findings --source hostile-review --dry-run

# With parent epic
/auto-ticket-from-findings --source contract-sweep --parent OMN-6724

# Only critical and major
/auto-ticket-from-findings --source dod-sweep --severity-threshold major
```

## Findings Input Format

The skill accepts findings in the standard severity-bucketed format used across all
sweep and review skills:

```json
{
  "source": "contract-sweep",
  "repo": "omniclaude",
  "timestamp": "2026-03-26T19:00:00Z",
  "findings": {
    "critical": [
      {
        "id": "CS-001",
        "file": "src/omniclaude/nodes/node_example.py",
        "line": 1,
        "description": "Missing contract YAML for node_example",
        "keyword": "missing contract",
        "context": "Node has no corresponding contract.yaml file"
      }
    ],
    "major": [
      {
        "id": "CS-002",
        "file": "contracts/node_router.yaml",
        "line": 12,
        "description": "Contract missing required field: input_model",
        "keyword": "missing field",
        "context": "Node contract must declare input_model"
      }
    ],
    "minor": [
      {
        "id": "CS-003",
        "file": "contracts/node_emit.yaml",
        "line": 5,
        "description": "Contract version outdated (0.1.0 vs current 1.0.0)",
        "keyword": "outdated version",
        "context": "contract_version should match current schema"
      }
    ],
    "nit": [
      {
        "id": "CS-004",
        "file": "contracts/node_emit.yaml",
        "line": 22,
        "description": "Description field could be more specific",
        "keyword": "vague description",
        "context": "Description says 'handles things' -- should specify what"
      }
    ]
  }
}
```

### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `source` | No | Source skill identifier (auto-detected from `--source` arg) |
| `repo` | No | Repository where findings were discovered |
| `timestamp` | No | When the sweep was run |
| `findings` | Yes | Object with severity buckets: `critical`, `major`, `minor`, `nit` |
| `findings.*.id` | No | Finding identifier (for dedup correlation) |
| `findings.*.file` | Yes | File path where the issue was found |
| `findings.*.line` | No | Line number (if applicable) |
| `findings.*.description` | Yes | Human-readable description of the issue |
| `findings.*.keyword` | No | Short keyword for search matching |
| `findings.*.context` | No | Additional context or rationale |

### Adapter: Hostile Review Format

The hostile-reviewer skill outputs findings in a slightly different format. The skill
auto-detects and converts:

```json
{
  "mode": "pr",
  "target": "433",
  "total_passes": 3,
  "convergence_verdict": "converged",
  "findings": [
    {
      "severity": "CRITICAL",
      "category": "architecture",
      "evidence": "Missing retry logic in event producer",
      "proposed_fix": "Add exponential backoff wrapper"
    }
  ],
  "per_model_severity_counts": {
    "codex": {"CRITICAL": 1, "MAJOR": 0, "MINOR": 0, "NIT": 0}
  }
}
```

Conversion rule: group by `severity` field into the standard buckets (case-insensitive).
Map `evidence` to `description`, map `proposed_fix` to `context`. The `category` field
is preserved as metadata but not used for dedup matching. Note: hostile-review findings
do not include `file`/`line` fields -- dedup falls back to keyword + description matching.

### Adapter: Contract Sweep Format

The contract-sweep skill outputs a YAML report. The skill auto-detects and converts:

```yaml
findings:
  - repo: omniclaude
    path: src/omniclaude/nodes/node_example.py
    severity: CRITICAL
    check: MISSING_CONTRACT
    message: "Node has no contract YAML"
```

Conversion rule: group by `severity` field, map `path` to `file`, map `message` to
`description`, map `check` to `keyword`.

### Adapter: DoD Sweep Format

The dod-sweep skill outputs per-ticket check results. The skill auto-detects and converts:

```json
{
  "ticket_id": "OMN-1234",
  "checks": {
    "CONTRACT_EXISTS": {"status": "FAIL", "detail": "No contract file found"},
    "RECEIPT_EXISTS": {"status": "PASS"},
    "RECEIPT_CLEAN": {"status": "SKIP"}
  }
}
```

Conversion rule: each `FAIL` check becomes a finding. Severity mapping:
- `CONTRACT_EXISTS` fail = critical
- `RECEIPT_EXISTS` fail = major
- `RECEIPT_CLEAN` fail = major
- `PR_MERGED` fail = minor
- `CI_GREEN` fail = major
- `DOD_ITEMS_MET` fail = minor

## Severity Filtering

| `--severity-threshold` | Findings Included |
|------------------------|-------------------|
| `critical` | Critical only |
| `major` | Critical + Major |
| `minor` (default) | Critical + Major + Minor |
| `nit` | All findings |

## Deduplication

Before creating any ticket, the skill queries Linear for existing tickets that match
the finding. A finding is considered a duplicate when it matches an open ticket with
the same source label, same file, and overlapping keyword or description:

### Dedup Strategy

```
For each finding:
  1. Search Linear by keyword + file path
  2. Search Linear by description substring (first 50 chars)
  3. Check source label match (same sweep type)
  4. If ANY search returns a matching open ticket → skip (dedup hit)
  5. If no match → create new ticket
```

### Keyword + File Search

```
mcp__linear-server__list_issues(
    query="{keyword} {basename(file)}",
    team="{team}",
    limit=10
)
```

### Description Similarity Check

For each returned issue, compare descriptions:

```python
def is_duplicate(existing_title: str, existing_desc: str, finding: dict) -> bool:
    """Check if an existing ticket covers this finding."""
    finding_file = finding.get("file", "")
    finding_desc = finding.get("description", "")
    finding_keyword = finding.get("keyword", "")

    # Exact file match in existing description
    file_match = finding_file and finding_file in (existing_desc or "")

    # Keyword appears in existing title or description
    keyword_match = finding_keyword and (
        finding_keyword.lower() in (existing_title or "").lower()
        or finding_keyword.lower() in (existing_desc or "").lower()
    )

    # Description substring match (first 50 chars normalized)
    desc_prefix = finding_desc[:50].lower().strip()
    desc_match = desc_prefix and desc_prefix in (existing_desc or "").lower()

    # A duplicate requires file match AND (keyword OR description match)
    return file_match and (keyword_match or desc_match)
```

### Source Label Filter

Only consider tickets with the same source label as potential duplicates:

```python
def has_source_label(issue: dict, source: str) -> bool:
    """Check if issue has the source label."""
    labels = [l.get("name", "").lower() for l in issue.get("labels", [])]
    return source.lower() in labels
```

If the existing ticket has a different source label (e.g., finding is from `dod-sweep`
but existing ticket is from `hostile-review`), it is NOT a duplicate -- the same file
can have different types of issues.

### Status Filter

Only open tickets count as duplicates. Closed/canceled tickets do not block creation:

```python
OPEN_STATES = {"backlog", "todo", "in progress", "triage", "unstarted"}

def is_open(issue: dict) -> bool:
    """Check if issue is in an open state."""
    return issue.get("status", "").lower() in OPEN_STATES
```

### Dedup Summary

After processing all findings, report dedup statistics:

```
Dedup Summary:
  Total findings: 12
  Duplicates skipped: 4
  New tickets to create: 8
  Breakdown:
    Critical: 2 new, 0 skipped
    Major: 3 new, 2 skipped
    Minor: 3 new, 2 skipped
```

## Ticket Creation

### Title Format

```
[{SOURCE}] [{SEVERITY}] {description} ({file}:{line})
```

Examples:
- `[contract-sweep] [CRITICAL] Missing contract YAML for node_example (node_example.py:1)`
- `[dod-sweep] [MAJOR] No DoD receipt found (OMN-1234)`
- `[hostile-review] [MINOR] Magic number should be constant (config.py:12)`

If no line number: omit the `:line` suffix.
If no file: omit the `(file:line)` suffix entirely.

### Description Template

```markdown
## Sweep Finding

**Source**: {source}
**Severity**: {severity}
**Keyword**: `{keyword}`
**Found**: {timestamp}

## Details

{description}

{context if available}

## Location

- **Repository**: {repo}
- **File**: `{file}`
- **Line**: {line or "N/A"}

## Definition of Done

- [ ] Issue addressed in code
- [ ] Tests added/updated if applicable
- [ ] Re-run `/{source}` to verify fix

---

## Contract

```yaml
# ModelTicketContract -- update ticket_id after creation; review inferred fields
schema_version: "1.0.0"
ticket_id: ""  # populate with the assigned OMN-XXXX after ticket is created
summary: "{description}"
is_seam_ticket: {inferred}
interface_change: false
interfaces_touched: {inferred}
contract_completeness: "stub"
evidence_requirements:
  - kind: "tests"
    description: "Unit tests pass"
    command: "uv run pytest tests/ -m unit -x"
  - kind: "ci"
    description: "CI pipeline green"
    command: "gh pr checks"
emergency_bypass:
  enabled: false
  justification: ""
  follow_up_ticket_id: ""
```

> After creation, set `ticket_id` to the assigned Linear ID and validate:
> `uv run python -c "from onex_change_control.models.model_ticket_contract import ModelTicketContract; import yaml; ModelTicketContract.model_validate(yaml.safe_load(open('contract.yaml').read()))"`
```

### Priority Mapping

| Severity | Linear Priority |
|----------|-----------------|
| Critical | 1 (Urgent) |
| Major | 2 (High) |
| Minor | 3 (Normal) |
| Nit | 4 (Low) |

### Labels

Every created ticket receives these labels:

| Label | Value |
|-------|-------|
| Source | `contract-sweep`, `dod-sweep`, or `hostile-review` |
| Severity | `critical`, `major`, `minor`, or `nit` |
| Origin | `auto-ticket` |
| Repo | Repository name (e.g., `omniclaude`) |

### Linear MCP Calls

```
mcp__linear-server__save_issue(
    title="{formatted_title}",
    teamId="{team_id}",
    description="{generated_description}",
    priority={priority_number},
    parentId="{parent}",           # if --parent provided
    projectId="{project_id}",     # if --project provided
    labelIds=["{source_label}", "{severity_label}", "{auto_ticket_label}", "{repo_label}"]
)
```

## Execution Flow

### Parse and Validate Input

```python
# Load findings from:
# 1. --findings arg (JSON string or file path)
# 2. Session context (from preceding sweep skill)
# 3. Error if neither available

if args.findings:
    if args.findings.endswith(".json") or args.findings.endswith(".yaml"):
        findings_data = load_from_file(args.findings)
    else:
        findings_data = json.loads(args.findings)
elif session_has_findings():
    findings_data = get_session_findings()
else:
    error("No findings available. Run a sweep first or provide --findings.")

# Auto-detect source if not specified
source = args.source or findings_data.get("source") or detect_source(findings_data)
if not source:
    error("Cannot determine source. Provide --source (contract-sweep | dod-sweep | hostile-review).")

# Auto-detect repo
repo = args.repo or findings_data.get("repo") or detect_current_repo()
```

### Normalize Findings

```python
# Convert from source-specific format to standard format
normalized = normalize_findings(findings_data, source)

# Apply severity threshold filter
threshold = args.severity_threshold or "minor"
severity_order = ["critical", "major", "minor", "nit"]
threshold_idx = severity_order.index(threshold)
included_severities = severity_order[:threshold_idx + 1]

filtered = {
    sev: findings
    for sev, findings in normalized.items()
    if sev in included_severities
}

total_findings = sum(len(v) for v in filtered.values())
print(f"Processing {total_findings} findings (threshold: {threshold})")
```

### Dedup Against Existing Tickets

```python
dedup_stats = {"total": 0, "skipped": 0, "new": 0, "by_severity": {}}
tickets_to_create = []

for severity, findings in filtered.items():
    new_count = 0
    skipped_count = 0

    for finding in findings:
        dedup_stats["total"] += 1

        # Search Linear for potential duplicates
        search_query = f"{finding.get('keyword', '')} {os.path.basename(finding.get('file', ''))}"
        existing = mcp__linear-server__list_issues(
            query=search_query.strip(),
            team=args.team or "Omninode",
            limit=10
        )

        # Check each result for duplicate match
        is_dup = False
        for issue in existing:
            if not is_open(issue):
                continue
            if not has_source_label(issue, source):
                continue
            if is_duplicate(issue["title"], issue.get("description", ""), finding):
                is_dup = True
                print(f"  DEDUP: '{finding['description'][:60]}...' matches {issue['id']}")
                break

        if is_dup:
            skipped_count += 1
            dedup_stats["skipped"] += 1
        else:
            new_count += 1
            dedup_stats["new"] += 1
            tickets_to_create.append({"severity": severity, "finding": finding})

    dedup_stats["by_severity"][severity] = {"new": new_count, "skipped": skipped_count}

# Print dedup summary
print(f"\nDedup Summary:")
print(f"  Total findings: {dedup_stats['total']}")
print(f"  Duplicates skipped: {dedup_stats['skipped']}")
print(f"  New tickets to create: {dedup_stats['new']}")
for sev, counts in dedup_stats["by_severity"].items():
    print(f"    {sev.title()}: {counts['new']} new, {counts['skipped']} skipped")
```

### Create Tickets (or Dry-Run)

```python
if args.dry_run:
    print(f"\n--- DRY RUN: Would create {len(tickets_to_create)} tickets ---\n")
    for item in tickets_to_create:
        title = format_title(item["finding"], item["severity"], source)
        print(f"  [{item['severity'].upper()}] {title}")
    return

# Rate-limit-aware batch creation (max 5 per batch with 1s delay)
created = []
failed = []
batch_size = 5

for i in range(0, len(tickets_to_create), batch_size):
    batch = tickets_to_create[i:i + batch_size]

    for item in batch:
        finding = item["finding"]
        severity = item["severity"]

        title = format_title(finding, severity, source)
        description = build_finding_description(finding, severity, source, repo)
        priority = severity_to_priority(severity)

        try:
            result = mcp__linear-server__save_issue(
                title=title,
                teamId=team_id,
                description=description,
                priority=priority,
                parentId=args.parent,    # if provided
                projectId=project_id,    # if provided
                labelIds=get_label_ids(source, severity, repo)
            )
            created.append({"id": result["identifier"], "title": title, "severity": severity})
        except Exception as e:
            failed.append({"title": title, "error": str(e)})

    # Rate limit pause between batches
    if i + batch_size < len(tickets_to_create):
        time.sleep(1)
```

### Report Results

```python
print(f"\n--- Results ---")
print(f"Created: {len(created)} tickets")
print(f"Failed: {len(failed)} tickets")
print(f"Skipped (dedup): {dedup_stats['skipped']} tickets")

if created:
    print(f"\nCreated tickets:")
    for t in created:
        print(f"  [{t['severity'].upper()}] {t['id']}: {t['title']}")

if failed:
    print(f"\nFailed tickets:")
    for t in failed:
        print(f"  {t['title']}: {t['error']}")
```

## Error Handling

| Error | Behavior |
|-------|----------|
| No findings available | Report error, suggest running a sweep first |
| Invalid findings format | Report parse error with expected format |
| Linear API error | Log error, continue with remaining findings |
| Rate limit hit | Pause 1s between batches of 5 to avoid hitting rate limits |
| Label not found | Create label if possible, warn if not |
| Source not detected | Report error, require `--source` arg |

**Never:**
- Create duplicate tickets (dedup is mandatory)
- Skip dedup checks in any mode except `--dry-run`
- Create tickets without the source label
- Silently drop findings without reporting

## Integration with Sweep Skills

### Composable Invocation

Sweep skills can invoke this skill directly after producing findings:

```python
# In contract-sweep SKILL.md:
# After producing findings, invoke auto-ticket:
/auto-ticket-from-findings --findings ./tmp/contract-sweep-findings.json --source contract-sweep --parent OMN-6724
```

### Pipeline Integration

In the ticket-pipeline, this skill can be chained after any sweep phase:

```
contract-sweep → auto-ticket-from-findings → ticket-work
dod-sweep → auto-ticket-from-findings → ticket-work
hostile-reviewer → auto-ticket-from-findings → ticket-work
```

## Examples

### Contract Sweep Follow-up
```bash
# Run contract sweep
/contract-sweep --repos omniclaude

# Auto-create tickets for findings
/auto-ticket-from-findings --source contract-sweep --parent OMN-6724 --project "Active Sprint"
```

### DoD Sweep Follow-up
```bash
# Run DoD sweep
/dod-sweep --since-days 7

# Create tickets for compliance gaps
/auto-ticket-from-findings --source dod-sweep --severity-threshold major
```

### Hostile Review Follow-up
```bash
# Run hostile review
/hostile-reviewer --pr 42 --repo OmniNode-ai/omniclaude

# Create tickets for unresolved findings
/auto-ticket-from-findings --source hostile-review --parent OMN-5000 --dry-run
```

### Full Autonomous Pipeline
```bash
# Sweep + auto-ticket in one pipeline
/contract-sweep --repos omniclaude && /auto-ticket-from-findings --source contract-sweep --parent OMN-6724
```

## See Also

- `/contract-sweep` -- ONEX contract health audit
- `/dod-sweep` -- DoD compliance sweep
- `/hostile-reviewer` -- Adversarial code review
- `/create-ticket` -- Create a single ticket manually
- `/create-followup-tickets` -- Create tickets from review session context
