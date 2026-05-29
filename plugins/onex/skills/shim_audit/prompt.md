# shim_audit prompt

You are executing the **shim_audit** skill.

## Announce

Say: "I'm using the shim-audit skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--dry-run` — default: false
- `--repos <names>` — comma-separated repo names; default: repos discovered by the backing node
- `--warn-days <n>` — default: 30

## Resolve repos

If `--repos` was not provided, let the backing node discover eligible repos.

## Scan each repo

For each repo path, dispatch:

```bash
uv run onex run-node node_shim_scanner --input '{
  "paths": ["<repo_path>/src"],
  "reference_date": null,
  "warn_days_before_expiry": <warn_days>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Report findings

Print a summary table:

| Status | Count |
|--------|-------|
| EXPIRED | N |
| EXPIRING | N |
| ACTIVE | N |

For EXPIRED findings, list: file, line, function, ticket_id, expires_on, replacement.

## Create tickets (skip if --dry-run)

For each EXPIRED finding:
1. The `ticket_id` field on the finding is the *tracking* ticket — check if it is already open in Linear.
2. If no open ticket exists, create one:
   - Title: `Remove expired @shim: <function_name> (<ticket_id>)`
   - Priority: High
   - Body includes: file_path, line_number, reason, replacement, expires_on

## Error handling

- Never run AST parsing or filesystem scans inline — always route through `node_shim_scanner`.
- On routing failure, raise `SkillRoutingError`; do not fall back.
