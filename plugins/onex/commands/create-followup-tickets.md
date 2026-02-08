---
name: create-followup-tickets
description: Create Linear tickets from code review issues found in the current session
tags: [linear, tickets, review, batch]
args:
  - name: project
    description: Linear project name (required, supports partial/fuzzy matching)
    required: true
  - name: from-file
    description: Path to review file (optional, uses session context by default)
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
---

# Create Follow-up Tickets from Code Review

Create Linear tickets from unresolved code review issues in the current session or a review file.

**Announce at start:** "Creating follow-up tickets from code review for project '{project}'."

## Execution

1. Parse arguments from `$ARGUMENTS`: `<project>`, `--from-file <path>`, `--repo <label>`, `--no-repo-label`, `--parent <id>`, `--include-nits`, `--only-critical`, `--only-major`, `--dry-run`, `--auto`, `--team <name>`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/create-followup-tickets/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Create follow-up tickets from code review",
  prompt="<POLY_PROMPT content>\n\n## Context\nPROJECT: {project}\nFROM_FILE: {from_file}\nREPO: {repo}\nNO_REPO_LABEL: {no_repo_label}\nPARENT: {parent}\nINCLUDE_NITS: {include_nits}\nONLY_CRITICAL: {only_critical}\nONLY_MAJOR: {only_major}\nDRY_RUN: {dry_run}\nAUTO: {auto}\nTEAM: {team}"
)
```

4. Report the created tickets summary to the user.
