# create_ticket prompt

You are executing the **create_ticket** skill.

## Announce

Say: "I'm using the create-ticket skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `title` — ticket title (mutually exclusive with --from-contract, --from-plan)
- `--from-contract <path>` — YAML contract file
- `--from-plan <path>` — plan markdown file
- `--milestone <id>` — milestone ID when using --from-plan
- `--repo <name>` — repository label
- `--parent <OMN-XXXX>` — parent epic
- `--blocked-by <ids>` — comma-separated blocking issue IDs
- `--team <name>` — default: Omninode
- `--dry-run` — default: false

## Dispatch

```bash
uv run onex run-node node_create_ticket --input '{
  "title": "<title or null>",
  "from_contract": "<path or null>",
  "from_plan": "<path or null>",
  "milestone": "<id or null>",
  "repo": "<repo or null>",
  "parent": "<id or null>",
  "blocked_by": "<ids or null>",
  "team": "<team>",
  "dry_run": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never create Linear tickets inline via MCP tools.
- On routing failure, raise `SkillRoutingError`; do not fall back.
