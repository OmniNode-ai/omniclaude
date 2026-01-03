---
name: pr-release-ready
description: Production PR review - Fixes ALL issues including nitpicks for release readiness
tags: [pr-review, production, release, github, automation]
---

# PR Release Ready - Fix ALL Issues

**Workflow**: Fetch issues (with nitpicks) -> **AUTO-RUN** `/parallel-solve` (all issues)

---

## Implementation Instructions

**CRITICAL**: This command automatically invokes `/parallel-solve` with ALL issues (including nitpicks).

**Steps**:

1. **Fetch collated issues** (including nitpicks):
   ```bash
   ~/.claude/skills/omniclaude/pr-review/collate-issues "${1:-}" --parallel-solve-format --include-nitpicks 2>&1
   ```

2. **Extract all actionable issues**:
   - Take sections: CRITICAL, MAJOR, MINOR, NITPICK
   - **EXCLUDE ONLY**: UNMATCHED section (these are unparseable comments)

3. **Auto-invoke /parallel-solve**:
   - Use the SlashCommand tool to invoke `/parallel-solve`
   - Pass ALL extracted issues (critical/major/minor/nitpick) as the command argument
   - Example: `/parallel-solve Fix all PR #33 review issues:\n\nCRITICAL:\n- [file:line] issue\n\nMAJOR:\n- [file:line] issue\n\nMINOR:\n- [file:line] issue\n\nNITPICK:\n- [file:line] issue`

**Note**: This command is for production releases. ALL feedback gets addressed (including nitpicks).
