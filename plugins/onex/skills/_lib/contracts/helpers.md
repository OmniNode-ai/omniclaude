# _lib/contracts/helpers.md

**Canonical contract schemas for all ticket, epic, plan, and triage skills.**

Every skill that creates, reads, or mutates tickets, epics, or plans MUST use these schemas.
Drift from these schemas is a skill-quality violation.

## Import

```
@_lib/contracts/helpers.md
```

---

## TicketContract

Canonical YAML schema for a single ticket. Used by:
- `plan-ticket` (generates template)
- `ticket-work` (embedded in Linear description)
- `linear-triage` (reads/writes ticket state)
- `linear-epic-org` (links tickets to epics)

### Schema

```yaml
# TicketContract v1
# ─────────────────────────────────────────────────────────────
# Identity
id: "OMN-XXXX"           # Linear ticket ID. null when drafting (pre-creation).
title: "..."             # Human-readable title (required)
repo: "omniclaude"       # Target repo slug. Options:
                         #   omnibase_compat | omnibase_core | omniclaude | omnibase_infra
                         #   omnidash | omniintelligence | omnimemory
                         #   omninode_infra | omnibase_spi | onex_change_control
                         #   cross-repo (for work spanning multiple repos)

# Hierarchy
epic_id: null            # Parent epic ID (OMN-XXXX) or null if unparented
parent_id: null          # Parent ticket ID for sub-tasks (null if none)

# Priority and state
priority: 3              # 1=Urgent  2=High  3=Normal  4=Low
state: "Backlog"         # Backlog | In Progress | In Review | Done | Cancelled

# Ticket-work phase (set/updated by ticket-work skill)
phase: "intake"          # intake | research | questions | spec
                         # implementation | review | done

# Requirements (what must be true)
requirements:
  - id: "R1"
    statement: "DESCRIBE WHAT MUST BE TRUE"
    rationale: "WHY THIS REQUIREMENT EXISTS"
    acceptance:
      - "HOW TO VERIFY THIS IS DONE"
      - "ANOTHER VERIFICATION CRITERION"

# Verification (how to confirm done)
verification:
  - id: "V1"
    title: "Unit tests pass"
    kind: "unit_tests"   # unit_tests | lint | typecheck | integration | manual | deploy_check
    command: "uv run pytest tests/"
    expected: "exit 0"
    blocking: true       # true = must pass before done; false = advisory

# Context (supporting research)
context:
  relevant_files: []     # List of file paths relevant to this ticket
  patterns_found: []     # List of discovered patterns or constraints
  notes: ""              # Free-form context notes

# Execution state (set by ticket-work and linear-triage)
execution:
  branch: null           # Git branch name (set at implementation start)
  pr_url: null           # GitHub PR URL (set when PR created)
  commits: []            # List of commit SHAs
  questions: []          # Clarifying questions (used in questions phase)
  gates: []              # Gate attestation tokens
```

### Minimal draft (for plan-ticket output)

```yaml
id: null
title: "YOUR TICKET TITLE HERE"
repo: "omniclaude"
epic_id: null
priority: 3
state: "Backlog"
requirements:
  - id: "R1"
    statement: "DESCRIBE WHAT MUST BE TRUE"
    rationale: "WHY THIS REQUIREMENT EXISTS"
    acceptance:
      - "HOW TO VERIFY THIS IS DONE"
verification:
  - id: "V1"
    title: "Unit tests pass"
    kind: "unit_tests"
    command: "uv run pytest tests/"
    expected: "exit 0"
    blocking: true
context:
  relevant_files: []
  patterns_found: []
  notes: ""
```

### Embedded form (for ticket-work in Linear description)

When embedded in a Linear ticket description, wrap in a fenced YAML block:

```markdown
---
## Contract

```yaml
id: "OMN-XXXX"
title: "..."
repo: "omniclaude"
epic_id: null
priority: 3
state: "In Progress"
phase: "implementation"
requirements: [...]
verification: [...]
context: {...}
execution:
  branch: "jonah/omn-xxxx-description"
  pr_url: null
  commits: []
  questions: []
  gates: []
```
```

---

## EpicContract

Canonical schema for an epic (parent grouping of tickets). Used by:
- `linear-epic-org` (creates and links epics)
- `ticket-plan --sync` (reads for MASTER_TICKET_PLAN.md generation)
- `linear-triage` (identifies orphaned tickets)

### Schema

```yaml
# EpicContract v1
id: "OMN-XXXX"           # Linear epic ID. null when drafting.
title: "..."             # Human-readable title (required)
emoji: "🔧"              # Display emoji for MASTER_TICKET_PLAN.md (single emoji)

# Status and priority (match Linear display values)
status: "In Progress"    # In Progress | Backlog | Done | Cancelled
priority: "High"         # High | Medium | Low | Urgent (display string)

# Description
scope: "What this epic delivers and why it matters"

# Affected repos (list of repo slugs)
repos:
  - "omniclaude"

# Child tickets (list of OMN-XXXX IDs, ordered by priority)
children: []

# Optional: links
links: []                # [{url: "...", title: "..."}]
```

### Grouping key (for linear-epic-org)

When grouping orphaned tickets into a proposed epic, the grouping key is:
- **Naming prefix**: tickets sharing `[repo] PREFIX-NN:` pattern (e.g., `DB-SPLIT-*`)
- **Repo + domain**: tickets in same repo with same domain label
- **Manual**: user-specified grouping

---

## PlanContract

Canonical structure for implementation plan documents. Used by:
- `design-to-plan` (generates plan documents)
- `executing-plans` (reads and executes plan tasks)

Plan documents live at: `docs/plans/YYYY-MM-DD-<feature-name>.md`

### Document header (required)

Every plan document MUST start with this header (no exceptions):

```markdown
# {Feature Name} Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** {One sentence describing what this builds}

**Architecture:** {2-3 sentences about approach and key design decisions}

**Tech Stack:** {Key technologies: Python 3.12, Pydantic v2, pytest, uv}

**Tickets:** {OMN-XXXX, OMN-YYYY}   ← linked Linear tickets (omit if none)

---
```

### Task structure (required for each task)

```markdown
### Task N: {Component Name}

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
```

### Field rules

| Field | Required | Notes |
|-------|----------|-------|
| `Feature Name` | Yes | Title-case, matches plan file name |
| `Goal` | Yes | Single sentence, no period at end |
| `Architecture` | Yes | 2-3 sentences max |
| `Tech Stack` | Yes | Comma-separated |
| `Tickets` | No | Omit line if no linked tickets |
| `Task N` | Yes (1+) | Sequential, no gaps |
| `Files` | Yes per task | Exact paths, not vague |
| `Steps` | Yes per task | TDD order: test → fail → implement → pass → commit |

---

## TriageReport

Output schema from `linear-triage`. Written to disk for review before apply phase.

Location: `~/.claude/state/linear-triage/{run_id}.yaml`

### Schema

```yaml
# TriageReport v1
run_id: "linear-triage-20260228-143012-a3f7b2"
generated_at: "2026-02-28T14:30:12Z"
threshold_days: 14       # tickets updated within this many days = "recent"

summary:
  total_scanned: 100
  recent_tickets: 60     # updated within threshold_days
  stale_tickets: 40      # updated before threshold_days
  marked_done: 5         # applied: marked done in Linear
  stale_flagged: 12      # flagged for human review (not applied)
  orphaned_tickets: 8    # tickets with no parent epic
  proposed_epics: 3      # new epics linear-epic-org should create

# Actions APPLIED (already written to Linear)
actions_applied:
  - ticket_id: "OMN-XXXX"
    title: "..."
    action: "marked_done"    # marked_done | no_change
    evidence: "PR #123 merged 2026-02-20: https://github.com/.../pull/123"
    pr_state: "merged"       # merged | closed | open | not_found

# Tickets flagged as stale (not yet actioned — human review needed)
stale_tickets:
  - ticket_id: "OMN-XXXX"
    title: "..."
    repo: "omniclaude"
    state: "In Progress"
    last_updated: "2025-12-01"
    age_days: 89
    recommendation: "review_and_close"  # review_and_close | keep_open | needs_context

# Orphaned tickets (no parent epic — input for linear-epic-org)
orphaned_tickets:
  - ticket_id: "OMN-XXXX"
    title: "..."
    repo: "omniclaude"
    state: "In Progress"
    proposed_epic_group: "DB-SPLIT"   # inferred grouping key (null if ambiguous)

# Recent tickets checked (PR status verified)
recent_checked:
  - ticket_id: "OMN-XXXX"
    title: "..."
    repo: "omniclaude"
    state: "In Progress"     # Linear state
    pr_state: "open"         # open | merged | closed | not_found
    pr_url: "https://..."    # null if not_found
    action: "no_change"      # no_change | marked_done
```

---

## Validation Rules

Skills MUST enforce these rules when creating or updating contracts:

### TicketContract
- `id` must match `/^OMN-\d+$/` or be `null` (draft)
- `repo` must be one of the listed repo slugs (omnibase_compat, omnibase_core, omniclaude, omnibase_infra, omnidash, omniintelligence, omnimemory, omninode_infra, omnibase_spi, onex_change_control, cross-repo)
- `priority` must be 1, 2, 3, or 4
- `state` must be one of: `Backlog | In Progress | In Review | Done | Cancelled`
- `phase` must be one of: `intake | research | questions | spec | implementation | review | done`
- `requirements` must have at least 1 item when `phase` >= `spec`
- `verification` must have at least 1 blocking item when `phase` >= `spec`
- `execution.branch` must match `/^jonah\/omn-\d+/` pattern when set

### EpicContract
- `id` must match `/^OMN-\d+$/` or be `null` (draft)
- `emoji` must be a single Unicode emoji character
- `status` must be one of: `In Progress | Backlog | Done | Cancelled`
- `priority` must be one of: `Urgent | High | Medium | Low`
- `repos` must be non-empty

### PlanContract
- Header must appear before any `### Task` section
- `Tickets:` line is optional but if present must list valid `OMN-XXXX` IDs
- Tasks must be numbered sequentially starting at 1
- Each task must have at least `Files:` and one step

---

## Schema Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-02-28 | Initial — unified TicketContract, EpicContract, PlanContract, TriageReport |

---

## See Also

- `plan-ticket` skill — generates TicketContract drafts
- `ticket-work` skill — executes against TicketContract embedded in Linear
- `design-to-plan` skill — generates PlanContract documents
- `linear-triage` skill — produces TriageReport, applies done-marking
- `linear-epic-org` skill — consumes orphaned_tickets from TriageReport
- `ticket-plan --sync` — reads EpicContract from Linear, updates MASTER_TICKET_PLAN.md
