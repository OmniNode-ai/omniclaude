---
name: local-review
description: Local code review loop that iterates through review, fix, commit cycles without pushing
version: 1.0.0
category: workflow
tags:
  - review
  - code-quality
  - local
  - iteration
author: OmniClaude Team
args:
  - name: --uncommitted
    description: Only review uncommitted changes (ignore committed)
    required: false
  - name: --since
    description: "Base ref for diff (branch/commit)"
    required: false
  - name: --max-iterations
    description: Maximum review-fix cycles (default 10)
    required: false
  - name: --files
    description: Glob pattern to limit scope
    required: false
  - name: --no-fix
    description: Report only, don't attempt fixes
    required: false
  - name: --no-commit
    description: Fix but don't commit (stage only)
    required: false
  - name: --checkpoint
    description: "Write checkpoint after each iteration (format: ticket_id:run_id)"
    required: false
  - name: --required-clean-runs
    description: "Number of consecutive clean runs required before passing (default 2, min 1)"
    required: false
---

# Local Review

## Overview

Review local changes, fix issues, commit fixes, and iterate until clean or max iterations reached.

**Workflow**: Gather changes -> Review -> Fix -> Commit -> Repeat until clean

**Announce at start:** "I'm using the local-review skill to review local changes."

> **Classification System**: Uses onex pr-review keyword-based classification (not confidence scoring).
> ALL Critical/Major/Minor issues MUST be resolved. Only Nits are optional.
> See: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md` for full priority definitions.

## Quick Start

```
/local-review                           # Review all changes since base branch
/local-review --uncommitted             # Only uncommitted changes
/local-review --since main              # Explicit base
/local-review --max-iterations 5        # Limit iterations
/local-review --files "src/**/*.py"     # Specific files only
/local-review --no-fix                  # Report only mode
/local-review --checkpoint OMN-2144:abcd1234  # Write checkpoints per iteration
/local-review --required-clean-runs 1         # Fast iteration (skip confirmation pass)
```

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--uncommitted` | false | Only review uncommitted changes (ignore committed) |
| `--since <ref>` | auto-detect | Base ref for diff (branch/commit) |
| `--max-iterations <n>` | 10 | Maximum review-fix cycles |
| `--files <glob>` | all | Glob pattern to limit scope |
| `--no-fix` | false | Report only, don't attempt fixes |
| `--no-commit` | false | Fix but don't commit (stage only) |
| `--checkpoint <ticket:run>` | none | Write checkpoint after each iteration (format: `ticket_id:run_id`) |
| `--required-clean-runs <n>` | 2 | Consecutive clean runs required before passing (min 1) |

## Dispatch Contracts (Execution-Critical)

**This section governs how you execute the review loop. Follow it exactly.**

You are an orchestrator. You manage the review loop, iteration tracking, and commit operations.
You do NOT review code or fix issues yourself. Both phases run in separate agents.

**Rule: The coordinator must NEVER call Edit(), Write(), or analyze code directly.**
If code review or fixes are needed, dispatch a polymorphic agent.

> **CRITICAL — subagent_type must be `"onex:polymorphic-agent"`** (with the `onex:` prefix).
> Using `"polymorphic-agent"` without the prefix will immediately fail with:
> `Error: Agent type 'polymorphic-agent' not found`

### Review Phase -- dispatch to polymorphic agent

For each iteration:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Review iteration {iteration+1} changes",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent. Do NOT delegate to feature-dev:code-reviewer.

    You are reviewing local code changes for production readiness.

    ## Changes to Review

    **Base ref**: {base_ref}
    **Files to review**: {file_list}
    **Mode**: {--uncommitted | all changes}

    # If --uncommitted mode:
    Run: git diff -- {files}  # Unstaged changes
    Also run: git diff --cached -- {files}  # Staged but uncommitted changes

    # If all changes mode (default):
    Run: git diff {base_ref}..HEAD -- {files}  # Committed changes
    Also run: git diff -- {files}  # Unstaged changes
    Also run: git diff --cached -- {files}  # Staged but uncommitted changes

    Read each changed file fully to understand context.

    ## Priority Classification (Keyword-Based)

    Classify issues using these keyword triggers (from onex pr-review):

    ### CRITICAL (Must Fix - BLOCKING)
    Keywords: security, vulnerability, injection, data loss, crash, breaking change, authentication bypass, authorization, secrets exposed

    ### MAJOR (Should Fix - BLOCKING)
    Keywords: bug, error, incorrect, wrong, fails, broken, performance, missing validation, race condition, memory leak

    ### MINOR (Should Fix - BLOCKING)
    Keywords: should, missing, incomplete, edge case, documentation

    ### NIT (Optional - NOT blocking)
    Keywords: nit, consider, suggestion, optional, style, formatting, nitpick

    ## Output Format

    Return issues in this exact JSON format:
    {\"critical\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
     \"major\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
     \"minor\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}],
     \"nit\": [{\"file\": \"path\", \"line\": 123, \"description\": \"issue\", \"keyword\": \"trigger\"}]}

    If no issues found, return: {\"critical\": [], \"major\": [], \"minor\": [], \"nit\": []}"
)
```

### Fix Phase -- dispatch to polymorphic agent (per severity)

For each severity with issues (critical first, then major, then minor):

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Fix {severity} issues from review",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

    Fix the following {severity} issues:

    {issues_list}

    **Instructions**:
    1. Read each file
    2. Apply the fix
    3. Verify the fix doesn't break other code
    4. Do NOT commit - just make the changes

    **Files to modify**: {file_list}"
)
```

### Commit Phase -- runs inline (lightweight git only)

No dispatch needed. The orchestrator handles git add + git commit directly.
Commit messages use the format: `fix(review): [{severity}] {summary}`

## Review Loop Summary

The skill runs a 3-phase loop:

1. **Review**: Dispatch polymorphic agent to classify issues by keyword
2. **Fix**: Dispatch polymorphic agent per severity (critical -> major -> minor)
3. **Commit**: Orchestrator stages and commits fixes inline

**Exit conditions**:
- N consecutive clean runs with stable run signature (default N=2; set via `--required-clean-runs`)
- Max iterations reached
- `--no-fix` mode (report only, exits after first review)
- Agent failure or parse failure (exits with warning status)

**Status indicators**:
- `Clean - Confirmed (N/N clean runs)` -- No blocking issues, confirmed by N consecutive clean runs
- `Clean with nits - Confirmed (N/N clean runs)` -- Blocking issues resolved, nits remain, confirmed by N clean runs
- `Clean run 1/2 - confirmation pass required` -- First clean run passed, awaiting confirmation
- `Max iterations reached` -- Hit limit with blocking issues remaining
- `Report only` -- `--no-fix` mode
- `Changes staged` -- `--no-commit` mode, fixes applied but not committed
- `Parse failed` / `Agent failed` / `Fix failed` / `Stage failed` / `Commit failed` -- Error states requiring manual intervention

## Detailed Orchestration

Full orchestration logic (phase details, argument parsing, error handling, JSON parsing with text
extraction fallback, state tracking, status selection logic, example session) is documented in
`prompt.md`. The dispatch contracts above are sufficient to execute the review loop.
Load `prompt.md` only if you need reference details for edge case handling or implementation notes.

## See Also

- `pr-review` skill (keyword-based priority classification reference)
- `ticket-pipeline` skill (chains local-review as Phase 2)
- `ticket-work` skill (implementation phase before review)
