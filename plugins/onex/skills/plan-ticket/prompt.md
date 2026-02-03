# Interactive Ticket Planning Orchestration

You are guiding users through interactive ticket creation. This prompt defines the complete orchestration logic using AskUserQuestion for all user interactions.

**Announce at start:** "I'm using the plan-ticket skill to help you create a well-structured ticket."

---

## Interactive Flow Overview

```
Step 1: Goal          -> What is the ticket about?
Step 2: Repository    -> Which codebase?
Step 3: Work Type     -> Feature, bug fix, refactor, etc.?
Step 4: Requirements  -> Iterative R1, R2, R3... collection
Step 5: Parent        -> Optional parent ticket
Step 6: Blocked By    -> Optional blocking tickets
Step 7: Project       -> Linear project selection
Step 8: Review        -> Show contract YAML preview
Step 9: Create        -> Delegate to /create-ticket
```

All user interactions MUST use AskUserQuestion. Never prompt for free text in regular messages.

---

## Step 1: Gather Goal

Start by understanding what the user wants to accomplish.

```
AskUserQuestion(questions=[{
    "question": "What's the goal of this ticket? Describe what you want to accomplish.",
    "header": "Ticket Goal",
    "allowFreeText": true
}])
```

Store response as `ticket_goal`. This becomes the ticket title.

---

## Step 2: Select Repository

```
AskUserQuestion(questions=[{
    "question": "Which repository is this for?",
    "header": "Repository",
    "options": [
        {"label": "omnibase_core", "description": "Core runtime, models, and validation"},
        {"label": "omniclaude", "description": "Claude Code plugin and hooks"},
        {"label": "omnibase_infra", "description": "Infrastructure and deployment"},
        {"label": "omnidash", "description": "Dashboard and monitoring UI"},
        {"label": "omniintelligence", "description": "Intelligence and RAG services"},
        {"label": "omnimemory", "description": "Memory and context services"},
        {"label": "omninode_infra", "description": "Node infrastructure"},
        {"label": "Other", "description": "Specify a different repository"}
    ],
    "multiSelect": false
}])
```

If user selects "Other":
```
AskUserQuestion(questions=[{
    "question": "Enter the repository name:",
    "header": "Custom Repository",
    "allowFreeText": true
}])
```

**Validation**: If response is empty or whitespace-only, ask again:
```python
if not custom_repo or not custom_repo.strip():
    print("Repository name cannot be empty. Please enter a valid name.")
    # Repeat the question
```

Store response as `ticket_repo`.

---

## Step 3: Select Work Type

```
AskUserQuestion(questions=[{
    "question": "What type of work is this?",
    "header": "Work Type",
    "options": [
        {"label": "Feature", "description": "New functionality or capability"},
        {"label": "Bug fix", "description": "Fix incorrect behavior"},
        {"label": "Refactor", "description": "Improve code without changing behavior"},
        {"label": "Documentation", "description": "Update or create documentation"},
        {"label": "Infrastructure", "description": "DevOps, CI/CD, or tooling changes"}
    ],
    "multiSelect": false
}])
```

Store response as `work_type`. Used for context in requirements.

---

## Step 4: Collect Requirements (Iterative)

Requirements are collected one at a time until the user signals completion.

### Initialize requirements list:
```python
requirements = []
requirement_count = 0
```

### Requirement collection loop:

```python
while True:
    requirement_count += 1

    # 4a: Get requirement statement
    AskUserQuestion(questions=[{
        "question": f"What is requirement R{requirement_count}? (Describe what must be true when this ticket is done)",
        "header": f"Requirement R{requirement_count}",
        "allowFreeText": true
    }])
    # Store as requirement_statement

    # Validate non-empty statement
    if not requirement_statement or not requirement_statement.strip():
        print("Requirement statement cannot be empty. Please provide a description.")
        # Repeat the question (decrement count and continue loop)

    # 4b: Get acceptance criteria
    AskUserQuestion(questions=[{
        "question": f"What are the acceptance criteria for R{requirement_count}? (How will we verify this requirement is met? Separate multiple criteria with commas.)",
        "header": f"Acceptance Criteria for R{requirement_count}",
        "allowFreeText": true
    }])
    # Store as acceptance_criteria_raw

    # Parse criteria (split by comma or newline)
    acceptance_criteria = [c.strip() for c in acceptance_criteria_raw.replace("\n", ",").split(",") if c.strip()]

    # Add to requirements list
    requirements.append({
        "id": f"R{requirement_count}",
        "statement": requirement_statement,
        "rationale": f"Required for {work_type.lower()}",
        "acceptance": acceptance_criteria
    })

    # 4c: Ask if more requirements
    AskUserQuestion(questions=[{
        "question": "Add another requirement?",
        "header": "More Requirements",
        "options": [
            {"label": "Yes", "description": "Add another requirement"},
            {"label": "No", "description": "Done adding requirements"}
        ],
        "multiSelect": false
    }])

    if response == "No":
        break
```

**Minimum requirement**: At least 1 requirement must be collected before proceeding.

---

## Step 5: Parent Ticket (Optional)

```
AskUserQuestion(questions=[{
    "question": "Does this ticket have a parent epic or feature ticket?",
    "header": "Parent Ticket",
    "options": [
        {"label": "Yes", "description": "Specify parent ticket ID"},
        {"label": "No", "description": "No parent ticket"}
    ],
    "multiSelect": false
}])
```

If "Yes":
```
AskUserQuestion(questions=[{
    "question": "Enter the parent ticket ID (e.g., OMN-1800):",
    "header": "Parent Ticket ID",
    "allowFreeText": true
}])
```

**Validation**: Ticket ID should match format `OMN-XXXX`:
```python
import re
if parent_ticket and not re.match(r'^OMN-\d+$', parent_ticket.strip()):
    print(f"Warning: '{parent_ticket}' doesn't match expected format (OMN-1234). Proceed anyway?")
    # Allow user to fix or continue
```

Store as `parent_ticket` or `null`.

---

## Step 6: Blocked By (Optional)

```
AskUserQuestion(questions=[{
    "question": "Is this ticket blocked by any other tickets?",
    "header": "Blocking Tickets",
    "options": [
        {"label": "Yes", "description": "Specify blocking ticket IDs"},
        {"label": "No", "description": "No blocking dependencies"}
    ],
    "multiSelect": false
}])
```

If "Yes":
```
AskUserQuestion(questions=[{
    "question": "Enter the blocking ticket IDs (comma-separated, e.g., OMN-1801, OMN-1802):",
    "header": "Blocking Ticket IDs",
    "allowFreeText": true
}])
```

**Validation**: Parse and validate each ticket ID:
```python
import re
blocked_by = []
for id_str in blocked_by_raw.split(","):
    id_str = id_str.strip()
    if id_str:
        if not re.match(r'^OMN-\d+$', id_str):
            print(f"Warning: '{id_str}' doesn't match expected format (OMN-1234). Skipping.")
        else:
            blocked_by.append(id_str)
```

Store as `blocked_by` list or empty list.

---

## Step 7: Select Project

First, fetch recent projects with error handling:
```python
try:
    projects = mcp__linear-server__list_projects(team="Omninode", limit=10)
except Exception as e:
    print(f"Warning: Could not fetch projects from Linear: {e}")
    projects = []  # Fall back to manual entry
```

Build options from results (or allow manual entry if API failed):
```
AskUserQuestion(questions=[{
    "question": "Which Linear project should this ticket be added to?",
    "header": "Linear Project",
    "options": [
        {"label": "{project_1.name}", "description": "{project_1.description or 'No description'}"},
        {"label": "{project_2.name}", "description": "{project_2.description or 'No description'}"},
        ...
        {"label": "None", "description": "Don't add to a project"},
        {"label": "Other", "description": "Specify a different project name"}
    ],
    "multiSelect": false
}])
```

If "Other":
```
AskUserQuestion(questions=[{
    "question": "Enter the project name:",
    "header": "Project Name",
    "allowFreeText": true
}])
```

Store as `project_name` or `null`.

---

## Step 8: Review Contract Preview

### Build contract YAML:

```yaml
title: "{ticket_goal}"
repo: "{ticket_repo}"
requirements:
  - id: "R1"
    statement: "{requirement_1_statement}"
    rationale: "{requirement_1_rationale}"
    acceptance:
      - "{criterion_1}"
      - "{criterion_2}"
  - id: "R2"
    statement: "{requirement_2_statement}"
    rationale: "{requirement_2_rationale}"
    acceptance:
      - "{criterion_1}"
# ... additional requirements
verification:
  - id: "V1"
    title: "Unit tests pass"
    kind: "unit_tests"
    command: "uv run pytest tests/"
    expected: "exit 0"
    blocking: true
  - id: "V2"
    title: "Lint passes"
    kind: "lint"
    command: "uv run ruff check ."
    expected: "exit 0"
    blocking: true
context:
  relevant_files: []
  patterns_found: []
  notes: ""
```

### Present preview:

Display the generated YAML in a code block:

```
Here's the contract that will be created:

---

**Title**: {ticket_goal}
**Repository**: {ticket_repo}
**Type**: {work_type}

**Requirements**:
{foreach requirement}
- **{requirement.id}**: {requirement.statement}
  - Acceptance: {foreach criterion} "{criterion}" {endforeach}
{endforeach}

**Verification**:
- V1: Unit tests pass (`uv run pytest tests/`)
- V2: Lint passes (`uv run ruff check .`)

**Parent**: {parent_ticket or "None"}
**Blocked by**: {blocked_by or "None"}
**Project**: {project_name or "None"}

---

```yaml
{generated_yaml}
```
```

### Confirm:

```
AskUserQuestion(questions=[{
    "question": "Does this look correct?",
    "header": "Review Contract",
    "options": [
        {"label": "Yes, create the ticket", "description": "Proceed with ticket creation"},
        {"label": "No, I need to make changes", "description": "Go back and edit"}
    ],
    "multiSelect": false
}])
```

If "No, I need to make changes":
```
AskUserQuestion(questions=[{
    "question": "What would you like to change?",
    "header": "Edit Contract",
    "options": [
        {"label": "Title/Goal", "description": "Change the ticket title"},
        {"label": "Repository", "description": "Change the repository"},
        {"label": "Requirements", "description": "Add, edit, or remove requirements"},
        {"label": "Parent ticket", "description": "Change parent ticket"},
        {"label": "Blocked by", "description": "Change blocking tickets"},
        {"label": "Project", "description": "Change Linear project"},
        {"label": "Start over", "description": "Begin from scratch"}
    ],
    "multiSelect": false
}])
```

Route back to appropriate step based on selection.

---

## Step 9: Create Ticket via /create-ticket

### Write contract to scratchpad:

```python
import os
import yaml
from pathlib import Path

# Determine scratchpad path
# Pattern: /private/tmp/claude/{encoded-cwd}/{session-id}/scratchpad/
session_id = os.environ.get("CLAUDE_SESSION_ID", "default")
cwd_encoded = os.getcwd().replace("/", "-").lstrip("-")
scratchpad_dir = Path(f"/private/tmp/claude/{cwd_encoded}/{session_id}/scratchpad")
scratchpad_dir.mkdir(parents=True, exist_ok=True)

contract_path = scratchpad_dir / "contract.yaml"

# Build contract dictionary
contract = {
    "title": ticket_goal,
    "repo": ticket_repo,
    "requirements": requirements,
    "verification": [
        {
            "id": "V1",
            "title": "Unit tests pass",
            "kind": "unit_tests",
            "command": "uv run pytest tests/",
            "expected": "exit 0",
            "blocking": True
        },
        {
            "id": "V2",
            "title": "Lint passes",
            "kind": "lint",
            "command": "uv run ruff check .",
            "expected": "exit 0",
            "blocking": True
        }
    ],
    "context": {
        "relevant_files": [],
        "patterns_found": [],
        "notes": ""
    }
}

# Write YAML
with open(contract_path, "w") as f:
    yaml.dump(contract, f, default_flow_style=False, sort_keys=False)
```

### Invoke /create-ticket:

Build the command arguments:

```python
args = f"--from-contract {contract_path} --team Omninode"

if parent_ticket:
    args += f" --parent {parent_ticket}"

if blocked_by:
    blocked_by_str = ",".join(blocked_by)
    args += f" --blocked-by {blocked_by_str}"

if project_name and project_name != "None":
    args += f" --project {project_name}"
```

Execute:
```
Skill(skill="create-ticket", args="{args}")
```

### Report success:

After /create-ticket completes, report the result:

```
Ticket created successfully!

  ID: {ticket_id}
  Title: {ticket_goal}
  URL: {ticket_url}

You can now use `/ticket-work {ticket_id}` to execute this ticket.
```

---

## Contract Schema Reference

The contract YAML must match this schema (compatible with /create-ticket):

```yaml
# Required
title: string              # Ticket title (from goal)
repo: string               # Repository name

# Requirements (at least 1 required)
requirements:
  - id: string             # R1, R2, R3...
    statement: string      # What must be true
    rationale: string      # Why this requirement exists
    acceptance:            # How to verify
      - string
      - string

# Default verification steps (auto-added)
verification:
  - id: string             # V1, V2...
    title: string          # Human-readable title
    kind: string           # unit_tests | lint | mypy | integration | manual_check | script
    command: string        # Shell command to run
    expected: string       # Expected result (e.g., "exit 0")
    blocking: boolean      # Whether failure blocks completion

# Context (optional, can be empty)
context:
  relevant_files: []       # Files that will be modified
  patterns_found: []       # Patterns to follow
  notes: string            # Additional notes
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| No requirements provided | Refuse to create ticket, require at least 1 |
| Invalid parent ticket ID | Report error, allow retry |
| Invalid blocked-by IDs | Report error, allow retry |
| Contract write fails | Report error, suggest manual creation |
| /create-ticket fails | Report error with details from downstream |
| Project not found | Warn user, offer to proceed without project |

**Never:**
- Create a ticket without at least one requirement
- Skip the review step
- Proceed after user says "No, I need to make changes"
- Call Linear MCP directly (always delegate to /create-ticket)

---

## Default Verification Steps

Always include these default verification steps:

1. **V1: Unit tests pass**
   - kind: `unit_tests`
   - command: `uv run pytest tests/`
   - expected: `exit 0`
   - blocking: `true`

2. **V2: Lint passes**
   - kind: `lint`
   - command: `uv run ruff check .`
   - expected: `exit 0`
   - blocking: `true`

Additional verification steps can be added based on work type:

- **Feature**: Consider adding integration tests
- **Infrastructure**: Consider adding deployment verification
- **Documentation**: Consider adding link validation

---

## State Management

Track collected information throughout the flow:

```python
@dataclass
class PlanTicketState:
    # Step 1
    ticket_goal: str = ""

    # Step 2
    ticket_repo: str = ""

    # Step 3
    work_type: str = ""

    # Step 4
    requirements: list[dict] = field(default_factory=list)

    # Step 5
    parent_ticket: str | None = None

    # Step 6
    blocked_by: list[str] = field(default_factory=list)

    # Step 7
    project_name: str | None = None

    # Metadata
    current_step: int = 1
    created_ticket_id: str | None = None
    created_ticket_url: str | None = None
```

When user asks to edit a specific section, preserve all other state and return to that step.

---

## Example Complete Flow

```
User: /plan-ticket

Claude: I'm using the plan-ticket skill to help you create a well-structured ticket.

[AskUserQuestion: Goal]
User: Add rate limiting to the API endpoints

[AskUserQuestion: Repository]
User: omnibase_core

[AskUserQuestion: Work Type]
User: Feature

[AskUserQuestion: Requirement R1]
User: System must limit requests to 100 per minute per user

[AskUserQuestion: Acceptance Criteria R1]
User: Rate limit header returned, 429 response when exceeded

[AskUserQuestion: More Requirements]
User: Yes

[AskUserQuestion: Requirement R2]
User: Rate limit configuration must be adjustable per endpoint

[AskUserQuestion: Acceptance Criteria R2]
User: Configuration in YAML, no code changes needed to adjust limits

[AskUserQuestion: More Requirements]
User: No

[AskUserQuestion: Parent Ticket]
User: Yes

[AskUserQuestion: Parent Ticket ID]
User: OMN-1800

[AskUserQuestion: Blocked By]
User: No

[AskUserQuestion: Project]
User: API Improvements

[Contract Preview displayed]

[AskUserQuestion: Review]
User: Yes, create the ticket

Claude: Writing contract to scratchpad...
        Invoking /create-ticket...

        Ticket created successfully!

          ID: OMN-1850
          Title: Add rate limiting to the API endpoints
          URL: https://linear.app/omninode/issue/OMN-1850

        You can now use `/ticket-work OMN-1850` to execute this ticket.
```

---

## Integration Points

### Upstream
- User invokes `/plan-ticket`
- Skill reads from Linear projects list

### Downstream
- Writes contract YAML to scratchpad
- Delegates to `/create-ticket` for Linear creation
- Created ticket is ready for `/ticket-work`

### Related Skills
- `/create-ticket` - Direct ticket creation from contract
- `/ticket-work` - Execute ticket using contract-driven phases
- Linear MCP tools - Underlying Linear API access
