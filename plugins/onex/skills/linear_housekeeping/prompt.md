# linear_housekeeping prompt

You are executing the **linear_housekeeping** skill.

## Announce

Say: "I'm using the linear-housekeeping skill for a full ticket audit."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--team <name>` — default: Omninode
- `--dry-run` — default: false

## Dispatch

```bash
uv run onex run-node node_linear_triage --input '{
  "team": "<team>",
  "dry_run": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never query or mutate Linear tickets inline via MCP tools.
- On routing failure, raise `SkillRoutingError`; do not fall back.
