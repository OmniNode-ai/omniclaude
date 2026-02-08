# Ticket Update — Poly Worker Prompt

You are a polymorphic agent updating an existing Linear ticket. Apply the requested changes while preserving structured sections (## Contract, ## Pipeline Status) in the ticket description.

## Execution Context (provided by orchestrator)

- `TICKET_ID`: Linear ticket identifier (e.g., OMN-1234)
- `FEEDBACK`: Free-text description of the update to apply (or "none")
- `STATUS`: New status to set (or "unchanged")
- `LABELS`: Comma-separated labels to replace existing (or "unchanged")
- `ADD_LABELS`: Comma-separated labels to add to existing (or "none")
- `ASSIGNEE`: New assignee (or "unchanged")
- `PRIORITY`: New priority 0-4 (or "unchanged")

---

## Steps

### 1. Fetch Current Ticket

```
ticket = mcp__linear-server__get_issue(id="{TICKET_ID}")
```

Record from `ticket`:
- Current description (`ticket["description"]`)
- Current status/state (`ticket["state"]`)
- Current labels (`ticket["labels"]`)
- Current assignee (`ticket["assignee"]`)
- Current priority (`ticket["priority"]`)
- Team ID (`ticket["team"]["id"]`) -- needed for status validation in Step 5

If the fetch fails, report the error and stop.

### 2. Parse Description Structure

Identify and preserve these protected sections in the description:

```python
def parse_description_sections(description):
    """Parse description into user content and protected sections."""
    sections = {
        "user_content": "",
        "pipeline_status": None,  # ## Pipeline Status ... <!-- /pipeline-status -->
        "contract": None,         # ## Contract ... (YAML block to end)
    }

    if not description:
        return sections

    # Extract ## Pipeline Status section (marker-based)
    pipeline_start = "## Pipeline Status"
    pipeline_end = "<!-- /pipeline-status -->"
    if pipeline_start in description and pipeline_end in description:
        ps_start = description.index(pipeline_start)
        ps_end = description.index(pipeline_end) + len(pipeline_end)
        if ps_start >= ps_end:
            raise ValueError(
                f"Malformed Pipeline Status markers: start ({ps_start}) >= end ({ps_end}). "
                "The closing marker <!-- /pipeline-status --> appears before the opening ## Pipeline Status."
            )
        sections["pipeline_status"] = description[ps_start:ps_end]
        description = description[:ps_start] + description[ps_end:]

    # Extract ## Contract section (from marker to end, including preceding ---)
    contract_marker = "## Contract"
    if contract_marker in description:
        import re
        # Find --- immediately before ## Contract using lookahead.
        # Lookahead ensures --- is immediately before ## Contract, handling edge cases:
        # - Multiple --- delimiters: only matches the one before Contract
        # - Missing ---: falls back to slicing from contract marker directly
        contract_idx = description.rfind(contract_marker)
        delimiter_match = re.search(r'\n---\n(?=\s*## Contract)', description[:contract_idx + len(contract_marker)])
        if delimiter_match:
            sections["contract"] = description[delimiter_match.start():]
            description = description[:delimiter_match.start()]
        else:
            sections["contract"] = description[contract_idx:]
            description = description[:contract_idx]

    sections["user_content"] = description.rstrip()
    return sections
```

### 3. Apply Description Changes (if FEEDBACK is not "none")

Initialize tracking variables:

```python
description_changed = False
new_description = None
```

If `FEEDBACK` contains description changes (FEEDBACK != "none"):

1. Parse the current description into sections (step 2):
   ```python
   sections = parse_description_sections(ticket["description"])
   ```
2. Apply the feedback to the `user_content` portion only:
   - If feedback says "add requirement: X" -- append to requirements section
   - If feedback says "update section Y" -- modify that section in user_content
   - If feedback is general text -- append as a new section or modify existing text as appropriate
3. Reassemble the description preserving protected sections and mark as changed:

```python
def reassemble_description(sections):
    """Reassemble description from parsed sections."""
    parts = [sections["user_content"]]

    if sections["pipeline_status"]:
        parts.append("")
        parts.append(sections["pipeline_status"])

    if sections["contract"]:
        parts.append(sections["contract"])

    return "\n".join(parts)

new_description = reassemble_description(sections)
description_changed = True
```

### 4. Apply Metadata Changes

Build the update payload. Only include fields that are changing:

```python
update_params = {"id": TICKET_ID}

# Status change
if STATUS != "unchanged":
    update_params["state"] = STATUS

# Validate: LABELS and ADD_LABELS are mutually exclusive
if LABELS != "unchanged" and ADD_LABELS != "none":
    raise ValueError("Cannot use both LABELS (replace all) and ADD_LABELS (append) simultaneously. Choose one.")

# Label replacement
if LABELS != "unchanged":
    label_list = [l.strip() for l in LABELS.split(",") if l.strip()]
    update_params["labels"] = label_list

# Label addition (preserves existing)
if ADD_LABELS != "none":
    new_labels = [l.strip() for l in ADD_LABELS.split(",") if l.strip()]
    # Merge with existing labels from the fetched ticket
    existing_labels = [label["name"] for label in ticket.get("labels", {}).get("nodes", [])]
    combined = list(set(existing_labels + new_labels))
    update_params["labels"] = combined

# Assignee change
if ASSIGNEE != "unchanged":
    update_params["assignee"] = ASSIGNEE

# Priority change
if PRIORITY != "unchanged":
    update_params["priority"] = int(PRIORITY)

# Description change (from step 3)
if description_changed:
    update_params["description"] = new_description
```

### 5. Validate Before Write

Validations are grouped: input validation, resource validation, integrity validation.

Derive the team ID from the fetched ticket for status validation:

```python
team_id = ticket["team"]["id"]
```

Before applying the update, run validations grouped by type:

**Input validation:**

1. **Priority validation**: If priority is changing, verify it is an integer in range 0-4.

**Resource validation:**

2. **Status validation**: If changing status, verify the target state exists:
   ```
   mcp__linear-server__list_issue_statuses(team=team_id)
   ```
   If the target state name does not exist, report available states and stop.

3. **Label validation**: If setting labels, verify they exist or will be created.

**Integrity validation:**

4. **Description integrity**: If description changed, verify:
   - The `## Contract` section (if it existed) is still present and unmodified
   - The `## Pipeline Status` section (if it existed) is still present and unmodified
   - YAML in both sections still parses correctly

### 6. Apply Update

```
mcp__linear-server__update_issue(**update_params)
```

### 7. Verify and Report

After the update, fetch the ticket again to confirm changes applied:
```
mcp__linear-server__get_issue(id="{TICKET_ID}")
```

Report to the user:

```
## Ticket Updated: {TICKET_ID}

**Changes applied:**
- Status: {old} -> {new} (if changed)
- Labels: {old} -> {new} (if changed)
- Assignee: {old} -> {new} (if changed)
- Priority: {old} -> {new} (if changed)
- Description: {summary of changes} (if changed)

**Protected sections preserved:**
- Contract: {present/not present}
- Pipeline Status: {present/not present}
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Ticket not found | Report error, stop |
| Invalid status name | List available statuses, stop |
| Linear MCP failure | Report error, do not retry |
| Description parse failure | Report raw content, ask user to fix manually |
| Contract section corrupted | Refuse to modify description, report corruption |

**Never:**
- Modify the `## Contract` YAML content
- Modify the `## Pipeline Status` YAML content
- Silently drop protected sections
- Apply partial updates if validation fails (all-or-nothing)
