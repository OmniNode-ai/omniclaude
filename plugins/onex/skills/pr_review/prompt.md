# pr_review prompt

You are executing the **pr_review** skill.

## Announce

Say: "I'm using the pr-review skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `pr_number` (required) — PR number to review
- `repo` (required) — GitHub repo (owner/repo)
- `--dry-run` — default: false

## Dispatch

```bash
uv run onex run-node node_pr_review_bot --input '{
  "pr_number": <pr_number>,
  "repo": "<repo>",
  "dry_run": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never fetch PR diffs, post review comments, or run judge verification inline.
- On routing failure, raise `SkillRoutingError`; do not fall back to legacy bash scripts.
