# /onex:pr_review_bot — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ReviewVerdict]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex skill pr_review_bot [--pr-number <n>] [--repo <v>] [--reviewer-models <a,b>] [--judge-model <v>] [--severity-threshold <v>] [--max-findings-per-pr <n>] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--pr-number` | integer, required |
| `--repo` | string, required |
| `--reviewer-models` | string list |
| `--judge-model` | string |
| `--severity-threshold` | string |
| `--max-findings-per-pr` | integer |
| `--dry-run` | boolean, flag |

The command resolves the skill→node mapping, builds the payload, dispatches the
node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, `cd` anywhere, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `ReviewVerdict`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
