---
name: ticket-update
description: Update an existing Linear ticket - modify description, status, labels, assignee, or priority while preserving contract and pipeline sections
tags: [linear, tickets, update, automation]
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1807)
    required: true
  - name: feedback
    description: Free-text description of the update to apply
    required: false
  - name: --status
    description: New status (e.g., "In Progress", "Done", "Backlog")
    required: false
  - name: --labels
    description: Comma-separated labels to set (replaces existing)
    required: false
  - name: --add-labels
    description: Comma-separated labels to add (preserves existing)
    required: false
  - name: --assignee
    description: Assignee name, email, or "me"
    required: false
  - name: --priority
    description: Priority level (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)
    required: false
---

# Ticket Update

Update an existing Linear ticket while preserving structured sections (Contract, Pipeline Status).

**Announce at start:** "Updating ticket {ticket_id}..."

## Execution

1. Parse arguments from `$ARGUMENTS`:
   > **Parsing order**: Flags (e.g., `--status`, `--labels`) are extracted first. Remaining unmatched text is captured as `feedback`.
   - `ticket_id` (required, first positional arg)
   - Remaining non-flag text is captured as `feedback` (free-text update description). Flags like `--status` are extracted first; everything else is concatenated as feedback.
   - `--status STATUS`
   - `--labels LABELS` (comma-separated, replaces existing)
   - `--add-labels LABELS` (comma-separated, adds to existing)
   - `--assignee USER`
   - `--priority N`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/ticket-update/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Update ticket {ticket_id}",
  prompt="<POLY_PROMPT content>\n\n## Execution Context\nTICKET_ID: {ticket_id}\nFEEDBACK: {feedback or 'none'}\nSTATUS: {status or 'unchanged'}\nLABELS: {labels or 'unchanged'}\nADD_LABELS: {add_labels or 'none'}\nASSIGNEE: {assignee or 'unchanged'}\nPRIORITY: {priority or 'unchanged'}"
)
```

4. Report the update results to the user.
