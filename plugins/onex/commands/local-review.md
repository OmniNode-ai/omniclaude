---
name: local-review
description: Local code review loop that iterates through review, fix, commit cycles without pushing
tags: [review, code-quality, local, iteration]
args:
  - name: uncommitted
    description: Only review uncommitted changes (ignore committed)
    required: false
  - name: since
    description: Base ref for diff (branch/commit)
    required: false
  - name: max-iterations
    description: Maximum review-fix cycles (default 10)
    required: false
  - name: files
    description: Glob pattern to limit scope
    required: false
  - name: no-fix
    description: Report only, don't attempt fixes
    required: false
  - name: no-commit
    description: Fix but don't commit (stage only)
    required: false
---

# /local-review - Local Code Review Loop

Review local changes, fix issues, commit fixes, and iterate until clean or max iterations reached.

**Announce at start:** "Starting local review loop."

## Execution

1. Parse arguments from `$ARGUMENTS`: `--uncommitted`, `--since <ref>`, `--max-iterations <n>`, `--files <glob>`, `--no-fix`, `--no-commit`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/local-review/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Run local review loop on current changes",
  prompt="<POLY_PROMPT content>\n\n## Context\nUNCOMMITTED: {uncommitted}\nSINCE_REF: {since_ref}\nMAX_ITERATIONS: {max_iterations}\nFILES_GLOB: {files_glob}\nNO_FIX: {no_fix}\nNO_COMMIT: {no_commit}\nWORKING_DIR: {cwd}"
)
```

4. Report the review summary and final status to the user.
