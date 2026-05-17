# duplication_sweep prompt

You are executing the **duplication_sweep** skill.

## Announce

Say: "I'm using the duplication-sweep skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--checks <list>` — comma-separated check IDs (default: D1,D2,D3,D4)
- `--omni-home <path>` — workspace root (default: auto-detect)
- `--json` — emit machine-readable JSON output

## Dispatch

```bash
uv run onex run-node node_duplication_sweep --input '{
  "omni_home": "<path or null>",
  "checks": ["D1", "D2", "D3", "D4"]
}'
```

If the command exits non-zero, stop and surface the error directly. Do not produce prose.

## Error handling

- Never run D1–D4 checks inline via Bash or GitHub API calls.
- On routing failure, raise `SkillRoutingError`; do not fall back.
