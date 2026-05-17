# doc_freshness_sweep prompt

You are executing the **doc_freshness_sweep** skill.

## Announce

Say: "I'm using the doc-freshness-sweep skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repo <name>` — scan single repo (default: all repos)
- `--claude-md-only` — default: false
- `--broken-only` — default: false
- `--create-tickets` — default: false
- `--max-tickets <n>` — default: 10
- `--dry-run` — default: false

## Dispatch

```bash
uv run onex run-node node_doc_freshness_sweep --input '{
  "repo": "<repo or null>",
  "claude_md_only": <bool>,
  "broken_only": <bool>,
  "create_tickets": <bool>,
  "max_tickets": <n>,
  "dry_run": <bool>
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never reimplement doc scanning or staleness detection inline.
- On routing failure, raise `SkillRoutingError`; do not fall back to direct file reads.
