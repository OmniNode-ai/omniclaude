# /onex:platform_readiness — dispatch-only shim

Dispatch to `node_platform_readiness` in omnimarket. Do not aggregate probes
inline — the backing node owns contract/golden-chain/data-flow/runtime/
dashboard/cost/CI verification and freshness logic.

## Announce

"I'm running the platform readiness gate via node_platform_readiness."

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `--json` | unset |

## Dispatch

```bash
cd "$ONEX_REGISTRY_ROOT/omnimarket"  # local-path-ok: canonical omnimarket worktree

uv run onex run-node node_platform_readiness --input '{}'
```

Capture the JSON output from stdout. The node produces a
`ModelPlatformReadinessResult` with `overall`, `dimensions`, `blockers`,
and `degraded`.

## Post-dispatch: Render results

If `--json` was passed, surface the node JSON verbatim. Otherwise render
the markdown readiness report from the node output — do not recompute
status or freshness locally.

## Error handling

On non-zero exit from the module runner, a `SkillRoutingError` JSON
envelope is returned — surface it directly, do not produce prose. If the
node is unavailable, stop — do not fall back to inline probe aggregation.
