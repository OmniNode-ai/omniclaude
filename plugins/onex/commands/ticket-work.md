---
name: ticket-work
description: Contract-driven ticket execution with Linear integration - phased dispatch through intake, research, questions, spec, implementation, review, and done
tags: [linear, tickets, automation, workflow, contract-driven]
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1807)
    required: true
---

# Contract-Driven Ticket Execution

**Usage:** `/ticket-work <ticket_id>` (e.g., `/ticket-work OMN-1807`)

**Announce at start:** "I'm using the ticket-work command to work on {ticket_id}."

## Execution

1. Parse `ticket_id` from `$ARGUMENTS`. Validate format matches `^[A-Z]+-\d+$`.
2. Fetch the ticket: `mcp__linear-server__get_issue(id="{ticket_id}")`
3. Parse the contract from the ticket description (look for `## Contract` section with a YAML code block).
   - If no contract exists, the poly will create one during the intake phase.
4. Determine the current phase from the contract (`phase` field, default: `intake`).
5. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/ticket-work/POLY_PROMPT.md`

## Phase Loop

Phases execute in order: `intake` -> `research` -> `questions` -> `spec` -> `implementation` -> `review` -> `done`

For each phase starting from the current phase:

1. **Dispatch** to a polymorphic agent for the current phase:

```
Task(
  subagent_type="polymorphic-agent",
  description="Execute {phase} phase for {ticket_id}",
  prompt="<POLY_PROMPT content>\n\n## Execution Context\nTICKET_ID: {ticket_id}\nCURRENT_PHASE: {phase}\nTICKET_TITLE: {title}\nREPO: {repo}\nCONTRACT:\n```yaml\n{contract_yaml}\n```"
)
```

2. After the poly completes, **re-fetch** the ticket to get the updated contract.

3. **Human gate** before advancing to the next phase. The `intake -> research` transition is automatic (no gate). All others require explicit user approval:

| Transition | Gate Prompt |
|------------|-------------|
| intake -> research | *(automatic, no gate)* |
| research -> questions | "Research complete. Ready to proceed to questions phase?" |
| questions -> spec | "All questions answered. Ready to proceed to spec?" |
| spec -> implementation | "Spec approved. Ready to implement?" |
| implementation -> review | "Implementation complete. Ready for review?" |
| review -> done | "All verification passed. Ready to complete?" |

4. On **approval**: advance to next phase, dispatch next poly.
5. On **rejection**: stay in current phase. Ask the user what changes are needed, then re-dispatch the poly for the same phase.

## Completion

When the `done` phase poly completes, report the final ticket status to the user including PR URL, verification results, and any hardening tickets created.
