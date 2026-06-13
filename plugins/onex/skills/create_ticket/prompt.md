# /onex:create_ticket — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ModelCreateTicketResult]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex skill create_ticket [--title <v>] [--from-contract <v>] [--from-plan <v>] [--milestone <v>] [--repo <v>] [--parent <v>] [--blocked-by <a,b>] [--project <v>] [--team <v>] [--allow-arch-violation]
```

| Argument | Type |
|----------|------|
| `--title` | string |
| `--from-contract` | string |
| `--from-plan` | string |
| `--milestone` | string |
| `--repo` | string |
| `--parent` | string |
| `--blocked-by` | string list |
| `--project` | string |
| `--team` | string |
| `--allow-arch-violation` | boolean, flag |

The command resolves the skill→node mapping, builds the payload, dispatches the
node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, `cd` anywhere, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `ModelCreateTicketResult`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
