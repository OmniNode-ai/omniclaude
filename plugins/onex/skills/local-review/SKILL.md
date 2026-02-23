---
name: local-review
description: Local code review loop that iterates through review, fix, commit cycles without pushing
version: 2.0.0
category: workflow
tags:
  - review
  - code-quality
  - local
  - iteration
author: OmniClaude Team
composable: true
inputs:
  - name: since
    type: str
    description: Base ref for diff (branch/commit); auto-detected if omitted
    required: false
  - name: max_iterations
    type: int
    description: Maximum review-fix cycles (default 10)
    required: false
  - name: required_clean_runs
    type: int
    description: Consecutive clean runs required before passing (default 2)
    required: false
  - name: files
    type: str
    description: Glob pattern to limit scope
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to ~/.claude/skill-results/{context_id}/local-review.json"
    fields:
      - status: clean | clean_with_nits | max_iterations_reached | report_only | changes_staged | error
      - iterations_run: int
      - issues_remaining: dict (critical/major/minor/nit counts)
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
  - name: --path
    description: "Path to the git worktree to review. Auto-detected from linked worktrees (via git worktree list) when running from the main worktree."
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
/local-review --path ../worktrees/OMN-1234/myrepo  # Explicit worktree path
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
| `--path <dir>` | auto-detect | Path to the git worktree to review. Auto-detected via `git worktree list` when running from the main worktree. |

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

    **Working directory**: {path} (run all git commands from this directory)

    # If --uncommitted mode:
    Run: git -C {path} diff -- {files}  # Unstaged changes
    Also run: git -C {path} diff --cached -- {files}  # Staged but uncommitted changes

    # If all changes mode (default):
    Run: git -C {path} diff {base_ref}..HEAD -- {files}  # Committed changes
    Also run: git -C {path} diff -- {files}  # Unstaged changes
    Also run: git -C {path} diff --cached -- {files}  # Staged but uncommitted changes

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

    **Files to modify**: {file_list}
    **Working directory**: {path} (all file paths are relative to this directory)"
)
```

### Commit Phase -- runs inline (lightweight git only)

No dispatch needed. The orchestrator handles git add + git commit directly.
When `--path` is provided, all git commands use `git -C {path} add` / `git -C {path} commit`.
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
- Agent failure or parse failure after retry exhaustion (see Retry Policy below)

**Status indicators**:
- `Clean - Confirmed (N/N clean runs)` -- No blocking issues, confirmed by N consecutive clean runs
- `Clean with nits - Confirmed (N/N clean runs)` -- Blocking issues resolved, nits remain, confirmed by N clean runs
- `Clean run 1/2 - confirmation pass required` -- First clean run passed, awaiting confirmation
- `Max iterations reached` -- Hit limit with blocking issues remaining
- `Report only` -- `--no-fix` mode
- `Changes staged` -- `--no-commit` mode, fixes applied but not committed
- `Parse failed` / `Agent failed` / `Fix failed` / `Stage failed` / `Commit failed` -- Error states after retry exhaustion (manual re-invocation required)

## Retry Policy

Transient agent failures no longer cause hard exits. The orchestrator retries automatically:

### Retry Behavior

| Error Type | Description | Retry Policy |
|------------|-------------|--------------|
| `AGENT_FAILED` | Sub-agent Task() failure (network, resource, timeout) | Up to 2 retries before hard exit |
| `PARSE_FAILED` | Review agent response could not be parsed (JSON parsing and text extraction both failed) | Up to 2 retries before hard exit |

### Retry Procedure

```
Iteration N: Review phase dispatched
  → AGENT_FAILED received
  → Log: "Retry 1/2 for AGENT_FAILED at iteration N. Reason: {error}"
  → Re-dispatch review phase immediately (no sleep)
  → If AGENT_FAILED again: retry 2/2
  → If AGENT_FAILED again: hard exit with status: failed, reason in ModelSkillResult
  → Retry count resets on any successful iteration
```

Retry attempts are logged to the per-session notes file (if F3 notes are enabled).

### Hard Exit After Retry Exhaustion

After 2 retries with no success, the skill exits with:
```
status: failed
reason: "AGENT_FAILED after 2 retries: {last_error}"
```

This is a hard exit — no further iterations are attempted. Manual re-invocation required.

**Implementation note**: This retry policy is declared in the SKILL.md frontmatter and also
implemented in the orchestrator (see `prompt.md` Step 2.3). The frontmatter declaration informs
the node handler; the orchestrator logic in `prompt.md` implements the actual retry loop with
`retry_count` state tracking. Both must agree on `max_retries: 2`.

```yaml
retry_on:
  - AGENT_FAILED
  - PARSE_FAILED
max_retries: 2
```

## Per-Session Issue Notes (Audit Trail)

Every review/debug skill session maintains a notes file that persists investigation history
across disconnections and re-starts. Prior dead ends are surfaced before new investigation begins.

### Notes File Location

```
~/.claude/review-notes/{timestamp}-{branch}.md
```

Where `{timestamp}` is the session start in `YYYYMMDD-HHMMSS` format and `{branch}` is the
current git branch name (with `/` replaced by `-`).
When `--path` is provided, `{branch}` is derived from `git -C {path} rev-parse --abbrev-ref HEAD`.

### Notes Format (Append-Only)

Each iteration appends to the notes file (never overwrites). In-file iteration
timestamps use `YYYY-MM-DD HH:MM:SS ±HH:MM` (human-readable with timezone, distinct
from the filename `YYYYMMDD-HHMMSS` format):

```markdown
## Iteration 3 — 2026-02-21 14:32:00 +00:00

### Issues Found
- [MAJOR] [FIXED] src/api.py:45 - Missing validation on user input
- [MINOR] [FAILED] src/config.py:12 - Magic number (failed_fixes_count: 3)

### Suppressed
- tests/conftest.py:12 - asyncio_mode [fp_001]

### Auto-Flagged for Suppression
- src/utils.py:89 - lambda capture in loop (appeared 3x, adding to pending_review)
```

Fix status values: `[FIXED]` | `[FAILED]` | `[PENDING]` | `[SKIPPED]`

### Init Behavior

At skill start, if a notes file exists for the current branch (any timestamp), read the most
recent file before beginning investigation. This surfaces:
- Issues previously attempted and failed (avoid re-hitting dead ends)
- Suppressions already in effect
- Issues auto-flagged in prior sessions

### Notes in systematic-debugging

The `systematic-debugging` skill reads the branch notes file before root cause investigation.

## Detailed Orchestration

Full orchestration logic (phase details, argument parsing, error handling, JSON parsing with text
extraction fallback, state tracking, status selection logic, example session) is documented in
`prompt.md`. The dispatch contracts above are sufficient to execute the review loop.
Load `prompt.md` only if you need reference details for edge case handling or implementation notes.

## Skill Result Output

When invoked as a composable sub-skill (from ticket-pipeline, epic-team, or other orchestrators),
write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/local-review.json` on exit.

```json
{
  "skill": "local-review",
  "status": "clean_with_nits",
  "iterations_run": 3,
  "issues_remaining": {"critical": 0, "major": 0, "minor": 0, "nit": 2},
  "context_id": "{context_id}"
}
```

**Status values**: `clean` | `clean_with_nits` | `max_iterations_reached` | `report_only` | `changes_staged` | `error`

**On error** (agent failed, parse failed, fix failed): set `status: error`, include `error_message`.

When invoked directly by a human (`/local-review`), skip writing the result file.

## Error Recovery (Executable)

When an agent failure or unrecoverable error occurs during the fix phase:

**Auto-dispatch systematic-debugging:**

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="local-review: systematic-debugging on fix failure",
  prompt="A fix agent failed during local-review iteration {iteration}.
    Error: {error_details}

    Invoke: Skill(skill=\"onex:systematic-debugging\")

    Investigate root cause of the fix failure. Report: root cause, recommended fix, files involved."
)
```

This replaces the former advisory annotation `REQUIRED SUB-SKILL: systematic-debugging`.

## See Also

- `pr-review` skill (keyword-based priority classification reference)
- `ticket-pipeline` skill (chains local-review as Phase 2)
- `ticket-work` skill (implementation phase before review)
- `systematic-debugging` skill (auto-dispatched on fix failure)
