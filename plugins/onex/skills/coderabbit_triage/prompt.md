# coderabbit_triage prompt

You are executing the **coderabbit_triage** skill.

## Announce

Say: "I'm using the coderabbit-triage skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `repo` (required) — GitHub repo in `owner/name` format
- `pr` (required) — PR number to triage
- `--dry-run` — default: false

## Dispatch

```bash
uv run onex run-node node_coderabbit_triage --input '{
  "repo": "<repo>",
  "pr": <pr>,
  "dry_run": <dry_run>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never implement triage logic inline.
- Never post GitHub replies directly.
- On routing failure, raise `SkillRoutingError`; do not fall back to direct `gh` calls.
