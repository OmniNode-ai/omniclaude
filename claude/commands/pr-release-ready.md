# PR Release Ready - Fix ALL Issues

**Workflow**: Fetch issues (with nitpicks) → Fire `/parallel-solve` (all issues)

---

## Step 1: Run Helper Script

Execute the collate-issues helper with `--include-nitpicks` to get /parallel-solve-ready output:

```bash
./claude/skills/pr-review/collate-issues "${1:-}" --parallel-solve-format --include-nitpicks 2>&1
```

---

## Step 2: Fire Parallel-Solve

**Take the COMPLETE output from Step 1** and pass it directly to `/parallel-solve` (including nitpicks).

Example:
```
/parallel-solve Fix all PR #33 review issues:

🔴 CRITICAL:
- [file:line] issue description

🟠 MAJOR:
- [file:line] issue description

🟡 MINOR:
- [file:line] issue description

⚪ NITPICK:
- [file:line] issue description
```

**Note**: This command is for production releases. ALL feedback gets addressed (including nitpicks).
