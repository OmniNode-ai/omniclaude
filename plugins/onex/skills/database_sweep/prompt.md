# database_sweep prompt

You are executing the **database_sweep** skill.

## Announce

Say: "I'm using the database-sweep skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--dry-run` — default: false
- `--table <name>` — check single table only (default: all)
- `--staleness-threshold <hours>` — default: 24

## Dispatch

```bash
uv run onex run-node node_database_sweep --input '{
  "dry_run": <bool>,
  "table": "<name or null>",
  "staleness_threshold_hours": <n>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never run database queries or psql commands inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
