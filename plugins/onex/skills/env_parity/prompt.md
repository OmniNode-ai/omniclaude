<!-- routing-enforced: dispatches to node_env_parity_compute (stub). functionally-complete requires real node implementation. -->

# /onex:env_parity — dispatch-only shim

Dispatch to `node_env_parity_compute` in omnimarket. Do not reimplement env parity checks inline.

No inline orchestration, no LLM reasoning, no direct script execution — the node owns the full pipeline.

## Announce

Say: "I'm using the env-parity skill to dispatch node_env_parity_compute."

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| positional (subcommand) | `check` |
| `--checks <ids>` | `credential,ecr,infisical` |
| `--all-checks` | unset |
| `--namespace <ns>` | `onex-dev` |
| `--dry-run` | unset |
| `--create-tickets` | true |
| `--no-create-tickets` | unset |

Set `CREATE_TICKETS=true` unless `--no-create-tickets` is present. If
`--no-create-tickets` is present, set `NO_CREATE_TICKETS=true` and do not set
`CREATE_TICKETS`.

## Dispatch

```bash
onex run node_env_parity_compute -- \
  ${SUBCOMMAND:-check} \
  ${CHECKS:+--checks "$CHECKS"} \
  ${ALL_CHECKS:+--all-checks} \
  ${NAMESPACE:+--namespace "$NAMESPACE"} \
  ${DRY_RUN:+--dry-run} \
  ${CREATE_TICKETS:+--create-tickets} \
  ${NO_CREATE_TICKETS:+--no-create-tickets}
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement env parity checks inline. If the node is unavailable, stop — do not fall back to inline script execution, direct Kubernetes API calls, or prose orchestration.
