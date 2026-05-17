# auto_merge prompt

You are executing the **auto_merge** skill.

## Announce

Say: "I'm using the auto-merge skill to merge PR #{pr_number}."

## Parse arguments

Extract from `$ARGUMENTS`:

- `pr_number` (required) — PR number to merge
- `repo` (required) — GitHub repo slug (org/repo)
- `--strategy <squash|merge|rebase>` — default: squash
- `--gate-timeout-hours <n>` — default: 24
- `--no-delete-branch` — default: delete branch after merge
- `--ticket-id <OMN-XXXX>` — optional Linear ticket to mark Done

## Dispatch

```bash
uv run onex run-node node_auto_merge_effect --input '{
  "pr_number": <pr_number>,
  "repo": "<repo>",
  "strategy": "<strategy>",
  "gate_timeout_hours": <n>,
  "delete_branch": <bool>,
  "ticket_id": "<id or null>"
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never run `gh pr merge` inline.
- Never poll CI readiness inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
