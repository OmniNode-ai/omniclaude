# coverage_sweep prompt

You are executing the **coverage_sweep** skill.

## Announce

Say: "I'm using the coverage-sweep skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <list>` — comma-separated repo names (default: all Python repos)
- `--target <n>` — coverage target percent (default: 50)
- `--dry-run` — default: false
- `--max-tickets <n>` — default: 20
- `--force-rescan` — default: false

## Dispatch

```bash
uv run onex run-node node_coverage_sweep --input '{
  "repos": "<list or null>",
  "target": <n>,
  "dry_run": <bool>,
  "max_tickets": <n>,
  "force_rescan": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never run pytest or coverage measurements inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
