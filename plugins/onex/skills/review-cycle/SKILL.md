---
name: review-cycle
description: Guided local code review with human checkpoints and learning mode
version: 1.0.0
category: workflow
tags:
  - review
  - code-quality
  - interactive
  - iteration
author: OmniClaude Team
args:
  - name: --uncommitted
    description: Only review uncommitted changes
    required: false
  - name: --since
    description: "Base ref for diff (branch/commit)"
    required: false
  - name: --files
    description: Glob pattern to limit scope
    required: false
  - name: --no-learning
    description: Skip educational explanations in drill-down
    required: false
  - name: --auto
    description: Non-interactive mode. Reviews, fixes Critical+Major, commits, presents summary.
    required: false
---

# Review Cycle

## Overview

Guided local code review with human checkpoints at every phase transition. The user
controls scope, fix selection, and commit decisions. The orchestrator dispatches
all code work to polymorphic agents and never touches code itself.

**Workflow**: Scope selection -> Review -> Issue presentation -> Fix selection -> Fix execution -> Commit checkpoint -> Continue or done

**Contrast with local-review**: `local-review` is fully autonomous (loop until clean or max iterations). `review-cycle` pauses at every phase boundary for human approval, supports drill-down explanations, and allows per-file accept/reject.

**Announce at start:** "I'm using the review-cycle skill for guided local code review."

> **Classification System**: Uses onex pr-review keyword-based classification (not confidence scoring).
> ALL Critical/Major/Minor issues MUST be resolved. Only Nits are optional.
> See: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md` for full priority definitions.

## Quick Start

```
/review-cycle                           # Guided review of all changes
/review-cycle --uncommitted             # Only uncommitted changes
/review-cycle --since main              # Explicit base ref
/review-cycle --files "src/**/*.py"     # Specific files only
/review-cycle --no-learning             # Skip educational explanations
/review-cycle --auto                    # Non-interactive single pass
/review-cycle --auto --uncommitted      # Auto-fix uncommitted changes
```

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--uncommitted` | false | Only review uncommitted changes (ignore committed) |
| `--since <ref>` | auto-detect | Base ref for diff (branch/commit) |
| `--files <glob>` | all | Glob pattern to limit scope |
| `--no-learning` | false | Skip educational explanations in drill-down |
| `--auto` | false | Non-interactive mode: review, fix Critical+Major, commit, summary |

## Dispatch Contracts (Execution-Critical)

**This section governs how you execute the review cycle. Follow it exactly.**

You are an orchestrator. You manage human checkpoints, scope selection, and git operations.
You do NOT review code, fix issues, or explain code yourself.

**ORCHESTRATOR CONSTRAINTS:**

1. NEVER call Edit(), Write(), or Bash(code-modifying commands)
2. NEVER parse code snippets from review results (they will not exist -- information hiding)
3. ALL code review -> polymorphic-agent dispatch
4. ALL code fixes -> polymorphic-agent dispatch
5. ALL issue explanations (drill-down) -> polymorphic-agent dispatch
6. Git operations (stash, add, commit, restore) are orchestrator-only
7. On JSON parse failure from agent: retry dispatch once, then fail with error to user

### Review Phase -- dispatch to polymorphic agent

The review agent returns an OPAQUE WORK ORDER. No patches, no code snippets, no fix suggestions.

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Review code changes for review-cycle",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

    You are reviewing local code changes for a guided review cycle.

    ## Changes to Review

    **Base ref**: {base_ref}
    **Files to review**: {file_list}
    **Mode**: {--uncommitted | all changes}

    # If --uncommitted mode:
    Run: git diff -- {files}
    Also run: git diff --cached -- {files}

    # If all changes mode (default):
    Run: git diff {base_ref}..HEAD -- {files}
    Also run: git diff -- {files}
    Also run: git diff --cached -- {files}

    Read each changed file fully to understand context.

    ## Priority Classification (Keyword-Based)

    Classify issues using these keyword triggers:

    ### CRITICAL (Must Fix - BLOCKING)
    Keywords: security, vulnerability, injection, data loss, crash, breaking change, authentication bypass, authorization, secrets exposed

    ### MAJOR (Should Fix - BLOCKING)
    Keywords: bug, error, incorrect, wrong, fails, broken, performance, missing validation, race condition, memory leak

    ### MINOR (Should Fix - BLOCKING)
    Keywords: should, missing, incomplete, edge case, documentation

    ### NIT (Optional - NOT blocking)
    Keywords: nit, consider, suggestion, optional, style, formatting, nitpick

    ## Output Format (STRICT -- return ONLY this JSON, no prose)

    {
      \"issues\": [
        {
          \"id\": \"ISS-001\",
          \"severity\": \"CRITICAL\",
          \"file\": \"relative/path.py\",
          \"line_start\": 45,
          \"line_end\": 48,
          \"title\": \"One-line description of the issue\",
          \"keyword\": \"injection\"
        }
      ],
      \"summary_counts\": {
        \"critical\": 1,
        \"major\": 0,
        \"minor\": 0,
        \"nit\": 0
      },
      \"suggested_batches\": [
        {
          \"severity\": \"CRITICAL\",
          \"issue_ids\": [\"ISS-001\"]
        }
      ]
    }

    IMPORTANT:
    - Do NOT include code snippets, patches, or fix suggestions
    - Do NOT include explanatory prose outside the JSON
    - Assign sequential IDs: ISS-001, ISS-002, etc.
    - title must be a concise one-line description
    - If no issues: return empty issues array and zero counts"
)
```

### Fix Phase -- dispatch to polymorphic agent (per severity batch)

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Fix {severity} issues for review-cycle",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

    Fix the following {severity} issues. Apply changes to the working tree.

    Issues to fix:
    {issue_list_with_ids_files_lines_titles}

    IMPORTANT:
    - Do NOT commit changes (orchestrator handles git)
    - Do NOT stage changes (orchestrator handles git add)
    - Fix ONLY the listed issues, nothing else

    When done, return ONLY a JSON object matching this exact schema:
    {
      \"applied_issue_ids\": [\"ISS-001\"],
      \"skipped_issue_ids\": [],
      \"modified_files\": [\"src/auth.py\"],
      \"diffstat\": {
        \"files_changed\": 1,
        \"insertions\": 3,
        \"deletions\": 2
      },
      \"errors\": []
    }

    If an issue cannot be fixed, add it to skipped_issue_ids and add an entry to errors:
    {\"issue_id\": \"ISS-002\", \"reason\": \"Cannot determine correct fix without more context\"}

    Do NOT include explanatory prose outside the JSON."
)
```

### Explain Phase -- dispatch for drill-down (only when user selects "Review individually")

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Explain issue {issue_id} for user",
  prompt="Read {file}:{line_start}-{line_end}.
    Explain the issue titled '{title}' ({severity}).

    Include:
    1. **The Problem**: What is wrong in the current code
    2. **Why It Matters**: Security, quality, or correctness impact
    3. **Before**: The current problematic code
    4. **After**: What the fix looks like

    Format as markdown for display to the user.
    Do NOT apply any changes. This is explanation only."
)
```

### Commit Phase -- inline (no dispatch)

The orchestrator handles git operations directly. No agent dispatch needed for
`git stash`, `git add`, `git commit`, or `git restore`.

## Interactive Flow

The skill runs an 8-step checkpoint flow. Each numbered step either dispatches
an agent or pauses for human input via AskUserQuestion. In `--auto` mode,
all AskUserQuestion calls are skipped with pre-determined choices.

### Step 1: Scope Selection

**Skipped if `--auto`** (uses defaults: all changes since base branch).

AskUserQuestion with options:

1. "All changes since base branch" (default)
2. "Uncommitted only"
3. "Since specific commit/branch" (prompt for ref)
4. "Specific files" (prompt for glob pattern)

Maps the selection to the appropriate git diff command and file list.

### Step 1.5: Capture Restore Point

```bash
git stash push -m "review-cycle-restore-point"
```

If `git stash push` fails (e.g., nothing to stash, dirty stash state), warn the
user but continue without a restore point. The restore point enables "Discard all
changes" in Step 6.

### Step 2: Review Dispatch

Dispatch the review agent using the Review Phase template above.

Parse the JSON response. On parse failure:
1. Try extracting JSON from markdown code blocks (` ```json ... ``` `)
2. If that fails, retry the dispatch once with stronger JSON-only instructions
3. If retry fails, report error to user and exit the current iteration

### Step 3: Issue Presentation

Display a summary table:

```markdown
## Review Results

| Severity | Count | Blocking |
|----------|-------|----------|
| CRITICAL | {n}   | Yes      |
| MAJOR    | {n}   | Yes      |
| MINOR    | {n}   | Yes      |
| NIT      | {n}   | No       |

### Issues

#### CRITICAL
- ISS-001 | src/auth.py:45-48 | SQL injection in user query

#### MAJOR
- ISS-002 | src/utils.py:23-25 | Uncaught exception in parser

#### MINOR
- ISS-003 | src/config.py:12-12 | Magic number should be constant

#### NIT
- ISS-004 | src/models.py:56-56 | Unused import
```

**If `--auto`**: skip to Step 4 automatically (auto-selects Critical+Major).

> **Design decision**: `--auto` intentionally skips MINOR issues despite their BLOCKING
> classification in interactive mode. MINOR issues (edge cases, missing documentation,
> incomplete handling) frequently require human judgment about intent, acceptable tradeoffs,
> and project-specific context. Auto-fixing them risks introducing incorrect behavior or
> unnecessary churn. Critical and Major issues have unambiguous fixes (security holes,
> bugs, crashes) that are safe to auto-apply. MINOR issues are surfaced in the final
> summary for the user to address in a subsequent interactive pass.

**If no blocking issues**: report summary, skip to Step 8 (final summary).

### Step 4: Fix Selection

**Skipped if `--auto`** (auto-selects Critical+Major).

AskUserQuestion with options:

1. "All blocking issues (Critical+Major+Minor)"
2. "Critical only"
3. "Critical + Major"
4. "Report only (no fixes)"

If "Report only": skip to Step 8 (final summary).

### Step 5: Fix Execution (per severity batch)

For each selected severity (critical first, then major, then minor):

**a.** Dispatch the fix agent using the Fix Phase template above.

**b.** Parse the JSON response.

**c.** Display batch summary:
```
Fixed {n} {severity} issue(s) in {m} file(s) (+{insertions}/-{deletions})
```

**d.** If `--auto`: auto-approve, skip to staging (step f).

**e.** AskUserQuestion with options:

1. **"Apply all fixes in this batch"** -- proceed to staging
2. **"Review individually"** -- for each modified file:
   - If `--no-learning` is NOT set: dispatch the Explain Phase agent, display explanation
   - Show file diff: `git diff -- {file}`
   - AskUserQuestion per file: "Stage this file" / "Skip this file"
3. **"Discard batch"** -- `git restore --worktree {modified_files}`

**f.** Stage approved files:
```bash
git add {approved_files}
```

### Step 6: Commit Checkpoint

**If `--auto`**: auto-commit with message `fix(review-cycle): auto-fix {n} critical and {m} major issue(s)` and skip to Step 8.

AskUserQuestion with options:

1. **"Commit"** -- default message: `fix(review-cycle): fix {n} {severity} issue(s)`
2. **"Commit with custom message"** -- prompt for message
3. **"Stage only (don't commit)"** -- leave files staged, proceed
4. **"Discard current batch"** -- `git restore --staged --worktree {batch_modified_files}`
5. **"Discard all changes"** -- `git checkout -- . && git stash apply {restore_sha}` (restores pre-review state).

   > **WARNING**: `git checkout -- .` discards ALL uncommitted changes in the working tree, not just changes from this review cycle. If you used `--files` to scope the review to specific files, this option still destroys changes in ALL files. If you have unrelated uncommitted work, use the restore point approach ("Discard current batch" with per-batch `git restore`) or commit unrelated changes before starting the review cycle. The restore point only covers changes that were stashable at review start.

### Step 7: Continue Loop

**If `--auto`**: no loop, proceed to Step 8.

AskUserQuestion with options:

1. "Run another review iteration" -- go back to Step 2
2. "Done" -- proceed to Step 8
3. "Show summary" -- display current session stats, then re-ask

### Step 8: Final Summary

```markdown
## Review Cycle Complete

**Iterations**: {iteration_number}
**Total issues found**: {total_issues_found}
**Total issues fixed**: {total_issues_fixed}
**Remaining issues**: {remaining_count}

### Commits
1. abc1234 - fix(review-cycle): fix 1 critical issue
2. def5678 - fix(review-cycle): fix 2 major issues

### Remaining Issues (if any)
- ISS-005 | MINOR | src/config.py:12 | Magic number should be constant (user skipped)
- ISS-006 | NIT | src/models.py:56 | Unused import (optional)

**Status**: {status_indicator}
```

Clean up: `git stash drop` (if the review-cycle-restore-point stash still exists).

**Status indicators**:
- `Clean` -- No blocking issues found
- `Clean with nits` -- Blocking issues resolved, optional nits remain
- `Fixes committed` -- User committed fixes, some issues may remain
- `Fixes staged` -- User chose "Stage only", changes not committed
- `Report only` -- User chose not to fix
- `Auto-fix complete` -- `--auto` mode finished
- `Parse failed` -- Agent output could not be parsed after retry
- `Agent failed` -- Review or fix agent crashed

**Next steps guidance**: Suggest `git push`, running tests, or starting another iteration
as appropriate for the final status.

## Discard Mechanism

| Action | Mechanism | Scope |
|--------|-----------|-------|
| Discard current batch | `git restore --staged --worktree .` | Current fix batch only |
| Discard all | `git stash pop` | All changes since scope selection |

After a commit, the restore point is no longer needed for that batch. On final
summary, `git stash drop` cleans up the stash entry.

If the user commits batch 1 then discards batch 2: only batch 2 is discarded.
Batch 1's commit stands.

## Exit Conditions

- No blocking issues found (Step 3 -- all counts zero)
- User selects "Report only" (Step 4)
- User selects "Done" at continue loop (Step 7)
- `--auto` mode completes its single pass
- Agent failure after retry (Step 2 parse failure)

## Detailed Orchestration

Full orchestration logic (argument parsing details, JSON parsing with fallback,
state tracking across iterations, error recovery, example session, and `--auto`
mode specifics) is documented in `prompt.md`. The dispatch contracts and
interactive flow above are sufficient to execute the review cycle.
Load `prompt.md` only if you need reference details for edge case handling or
implementation notes.

## See Also

- `local-review` skill (fully autonomous review loop)
- `pr-review` skill (keyword-based priority classification reference)
- `ticket-pipeline` skill (chains local-review as Phase 2)
