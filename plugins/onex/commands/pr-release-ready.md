---
name: pr-release-ready
description: PR Release Ready - Fix ALL Issues
tags: [pr, github, automation, release]
---

# PR Release Ready - Fix ALL Issues

**Workflow**: Fetch issues (with nitpicks) → **AUTO-RUN** `/parallel-solve` (all issues)

---

## Implementation Instructions

**CRITICAL**: This command automatically invokes `/parallel-solve` with ALL issues (including nitpicks).

**Steps**:

1. **Fetch collated issues** (including nitpicks):
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format --include-nitpicks 2>&1
   ```

2. **Extract all actionable issues**:
   - Take sections: 🔴 CRITICAL, 🟠 MAJOR, 🟡 MINOR, ⚪ NITPICK
   - **EXCLUDE ONLY**: ❓ UNMATCHED section (these are unparseable comments)

3. **Auto-invoke /parallel-solve**:
   - Use the SlashCommand tool to invoke `/parallel-solve`
   - Pass ALL extracted issues (critical/major/minor/nitpick) as the command argument
   - Example: `/parallel-solve Fix all PR #33 review issues:\n\n🔴 CRITICAL:\n- [file:line] issue\n\n🟠 MAJOR:\n- [file:line] issue\n\n🟡 MINOR:\n- [file:line] issue\n\n⚪ NITPICK:\n- [file:line] issue`

**Note**: This command is for production releases. ALL feedback gets addressed (including nitpicks).
