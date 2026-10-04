# /onex:dod_verify — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ModelDodVerifyState]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex skill dod_verify "<ticket_id>" --execution-audience <hosted|local_done_gate> [--contract-path <v>] [--dry-run]
```

| Argument | Type |
|----------|------|
| `<ticket_id>` | positional, required |
| `--execution-audience` | `hosted` or `local_done_gate`, required |
| `--contract-path` | string |
| `--dry-run` | boolean, flag |

`--execution-audience` names the boundary that is running the verifier. Omit it and the node
refuses with `EXECUTION_AUDIENCE_REQUIRED` before it loads the contract or runs any evidence, so
the result says nothing about the ticket. Use `hosted` for a scheduled or CI run: it skips a
`dod_evidence` item declared `execution_scope: local_done_gate` as `NOT_EVALUATED`. Use
`local_done_gate` when this session is the local Done gate and may execute those items itself.

The command resolves the skill→node mapping, builds the payload, dispatches the
node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, `cd` anywhere, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `ModelDodVerifyState`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
