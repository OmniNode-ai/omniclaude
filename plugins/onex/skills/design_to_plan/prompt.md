# /onex:design_to_plan — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ModelDesignToPlanPhase3LaunchResult]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex skill design_to_plan [--phase <v>] [--topic <v>] [--plan-path <v>] [--no-launch] [--plan-only] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--phase` | string |
| `--topic` | string |
| `--plan-path` | string |
| `--no-launch` | boolean, flag |
| `--plan-only` | boolean, flag |
| `--dry-run` | boolean, flag |

The command resolves the skill→node mapping, builds the payload, dispatches the
node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, `cd` anywhere, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `ModelDesignToPlanPhase3LaunchResult`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
