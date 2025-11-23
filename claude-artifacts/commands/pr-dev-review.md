# PR Dev Review - Fix Critical/Major/Minor Issues

**Workflow**: Fetch issues → Fire `/parallel-solve` (non-nits) → Ask about nitpicks

---

## Step 1: Run Helper Script

Execute the collate-issues helper to get /parallel-solve-ready output:

```bash
~/.claude/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format 2>&1
```

---

## Step 2: Fire Parallel-Solve

**Take the output from Step 1** and pass it directly to `/parallel-solve`, **but EXCLUDE any ⚪ NITPICK sections**.

Example:
```
/parallel-solve Fix all PR #33 review issues:

🔴 CRITICAL:
- [file:line] issue description

🟠 MAJOR:
- [file:line] issue description

🟡 MINOR:
- [file:line] issue description
```

**IMPORTANT**: Do NOT include the ⚪ NITPICK section in the /parallel-solve command.

---

## Step 3: Ask About Nitpicks

After `/parallel-solve` completes, if there were nitpicks in the original output:

Ask the user: "Critical/major/minor issues are being addressed. There are [N] nitpick items. Address them now?"

If yes → Fire another `/parallel-solve` with just the nitpicks.
