# /onex:pr_polish — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ModelPrPolishCompletedEvent]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex skill pr_polish [--repo <v>] [--pr-number <n>] [--ticket-id <v>] [--required-clean-runs <n>] [--max-iterations <n>] [--skip-conflicts] [--skip-pr-review] [--skip-local-review] [--no-ci] [--no-push] [--no-automerge] [--dry-run]
```

| Argument | Type |
|----------|------|
| `--repo` | string, required |
| `--pr-number` | integer, required |
| `--ticket-id` | string |
| `--required-clean-runs` | integer |
| `--max-iterations` | integer |
| `--skip-conflicts` | boolean, flag |
| `--skip-pr-review` | boolean, flag |
| `--skip-local-review` | boolean, flag |
| `--no-ci` | boolean, flag |
| `--no-push` | boolean, flag |
| `--no-automerge` | boolean, flag |
| `--dry-run` | boolean, flag |

The command resolves the skill→node mapping, builds the payload, dispatches the
node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, `cd` anywhere, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `ModelPrPolishCompletedEvent`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
