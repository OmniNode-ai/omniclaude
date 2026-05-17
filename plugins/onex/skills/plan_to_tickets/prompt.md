# plan_to_tickets prompt

You are executing the **plan_to_tickets** skill.

## Announce

Say: "I'm using the plan-to-tickets skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `plan-file` (required) — path to plan markdown file
- `--project <name>` — Linear project name
- `--epic-title <title>` — epic title override
- `--no-create-epic` — default: false (auto-create epic if needed)
- `--dry-run` — default: false
- `--skip-existing` — default: false
- `--team <name>` — default: Omninode

## Dispatch

```bash
uv run onex run-node node_plan_to_tickets --input '{
  "plan_file": "<path>",
  "project": "<project or null>",
  "epic_title": "<title or null>",
  "no_create_epic": <bool>,
  "dry_run": <bool>,
  "skip_existing": <bool>,
  "team": "<team>"
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never parse plan files or create Linear tickets inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
