---
name: ticket-audit
description: Multi-repo ticket hygiene audit - finds stale, orphaned, unassigned, and duplicate tickets across Linear teams
tags: [linear, tickets, audit, hygiene, automation]
args:
  - name: --team
    description: Linear team name or ID to audit (defaults to all teams)
    required: false
  - name: --stale-days
    description: Days without update to consider stale (default 14)
    required: false
  - name: --fix
    description: Apply recommended fixes automatically (label stale tickets, flag orphans). Auto-closing is not performed.
    required: false
---

# Ticket Audit

Multi-repo ticket hygiene audit. Finds stale, orphaned, unassigned, and duplicate tickets across Linear teams.

**Announce at start:** "Running ticket audit..."

## Execution

1. Parse arguments from `$ARGUMENTS`:
   - `--team TEAM` (optional, defaults to all teams)
   - `--stale-days N` (optional, default 14)
   - `--fix` (optional, apply remediation)
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/ticket-audit/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Audit ticket hygiene across Linear teams",
  prompt="<POLY_PROMPT content>\n\n## Execution Context\nTEAM: {team or 'all'}\nSTALE_DAYS: {stale_days or '14'}\nFIX_MODE: {fix or 'false'}"
)
```

4. Report the audit findings and remediation report to the user.
