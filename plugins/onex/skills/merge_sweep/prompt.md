# /onex:merge_sweep — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ModelPrLifecycleResult]`
JSON to stdout — the full handler result, never truncated. RuntimeLocal logs and
intermediate context go to a capture file + the artifact store, never to you.

```bash
cd "$OMNI_HOME/omnibase_infra" && uv run onex skill merge_sweep [--repos <a,b>] [--dry-run] [--inventory-only] [--fix-only] [--merge-only] [--max-parallel-polish <n>] [--admin-fallback-threshold-minutes <n>] [--verify] [--verify-timeout-seconds <n>] # local-path-ok: merge_sweep dispatches from the canonical omnibase_infra checkout, not a ticket worktree
```

| Argument | Type |
|----------|------|
| `--repos` | string list |
| `--dry-run` | boolean, flag |
| `--inventory-only` | boolean, flag |
| `--fix-only` | boolean, flag |
| `--merge-only` | boolean, flag |
| `--max-parallel-polish` | integer |
| `--admin-fallback-threshold-minutes` | integer |
| `--verify` | boolean, flag |
| `--verify-timeout-seconds` | integer |

The command runs from `omnibase_infra` because that repository provides the
`onex skill` CLI. It resolves the skill→node mapping, builds the payload,
dispatches the node in receipt mode, and extracts the result internally. Do NOT construct a
payload file, change to any other directory, or read any intermediate result file.

## Present the result

Parse the single JSON object on stdout and present the typed `ModelSkillResult`:

- **Status**: `status` — `completed` | `failed` | `timeout`
- **Result**: `result` — the full `ModelPrLifecycleResult`; surface its fields directly.
- **Artifacts**: `artifact_refs` — retrieval handles for the captured runtime log + full result.

On non-zero exit the receipt's `result` carries the full error inline — surface
it directly. Do not fall back to an inline scan, probe, or orchestration.
