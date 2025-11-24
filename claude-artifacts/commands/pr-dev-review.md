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

After `/parallel-solve` completes, check the **Step 1 output** for any ⚪ NITPICK sections:

- If nitpicks were found in the original collate-issues output, ask the user:
  "Critical/major/minor issues are being addressed. There are [N] nitpick items from the PR review. Address them now?"

- If yes → Fire another `/parallel-solve` with just the nitpick items from the Step 1 output.

**Note**: Nitpicks are discovered from the Step 1 collate-issues output but excluded from Step 2's /parallel-solve command.
