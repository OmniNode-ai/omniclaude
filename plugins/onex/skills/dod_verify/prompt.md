# dod_verify prompt

You are executing the **dod_verify** skill.

## Announce

Say: "I'm using the dod-verify skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `ticket_id` (required) — Linear ticket ID (e.g., OMN-1234)
- `--contract-path <path>` — optional override path to contract YAML

## Dispatch

```bash
uv run onex run-node node_dod_verify --input '{
  "ticket_id": "<ticket_id>",
  "contract_path": "<path or null>"
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never reimplement evidence verification inline.
- On routing failure, raise `SkillRoutingError`; do not fall back.
