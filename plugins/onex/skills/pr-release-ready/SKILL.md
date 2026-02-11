---
name: pr-release-ready
description: PR Release Ready - Fix ALL Issues including nitpicks
version: 1.0.0
category: workflow
tags:
  - pr
  - review
  - release
  - code-quality
author: OmniClaude Team
args:
  - name: pr_url
    description: PR URL or number (auto-detects from branch)
    required: false
---

# PR Release Ready - Fix ALL Issues

**Workflow**: Fetch issues (with nitpicks) -> **AUTO-RUN** parallel-solve (all issues)

**Announce at start:** "I'm using the pr-release-ready skill to fix ALL PR issues including nitpicks."

## Dispatch Contracts (Execution-Critical)

You are an orchestrator. You gather and collate issues, then dispatch parallel-solve.
You do NOT fix issues yourself.

**Rule: NEVER call Edit() or Write() to fix PR issues.**

### Gather Phase -- inline

Fetch all PR review comments including nitpicks. No dispatch needed.

### Fix Phase -- dispatch via parallel-solve

```
Skill(skill="onex:parallel-solve")
```

Pass ALL collated issues (including nitpicks) as context.

---

## Implementation Instructions

**CRITICAL**: This skill automatically invokes parallel-solve with ALL issues (including nitpicks).

**Steps**:

1. **Fetch collated issues** (including nitpicks):
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format --include-nitpicks 2>&1
   ```

2. **Extract all actionable issues**:
   - Take sections: CRITICAL, MAJOR, MINOR, NITPICK
   - **EXCLUDE ONLY**: UNMATCHED section (these are unparseable comments)

3. **Auto-invoke parallel-solve**:
   - Dispatch parallel-solve with ALL extracted issues (critical/major/minor/nitpick)
   - Example context: "Fix all PR #33 review issues:\n\nCRITICAL:\n- [file:line] issue\n\nMAJOR:\n- [file:line] issue\n\nMINOR:\n- [file:line] issue\n\nNITPICK:\n- [file:line] issue"

**Note**: This skill is for production releases. ALL feedback gets addressed (including nitpicks). This is the same as pr-review-dev but without the nitpick deferral -- everything is fixed in one pass.
