# /onex:doc_freshness_sweep — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[DocFreshnessSweepResult]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex skill doc_freshness_sweep [--omni-home <v>] [--repos <a,b>] [--claude-md-only] [--broken-only] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--omni-home` | string |
| `--repos` | string list |
| `--claude-md-only` | boolean, flag |
| `--broken-only` | boolean, flag |
| `--dry-run` | boolean, flag |

The command resolves the skill→node mapping, builds the payload, dispatches the
node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, `cd` anywhere, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `DocFreshnessSweepResult`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
