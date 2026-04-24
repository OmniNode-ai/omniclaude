# /onex:session — dispatch-only shim

Dispatch to `node_session_orchestrator` in omnimarket. Do not reimplement phases inline.

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `--mode <interactive\|autonomous>` | `interactive` |
| `--phase <0\|1\|2\|3>` | `0` |
| `--dry-run` | unset |
| `--skip-health` | unset |
| `--standing-orders <path>` | `.onex_state/session/standing_orders.json` |

## Dispatch

```bash
cd "$ONEX_REGISTRY_ROOT/omnimarket"  # local-path-ok: canonical omnimarket worktree
uv run onex run node_session_orchestrator -- \
  --mode "${MODE:-interactive}" \
  --phase "${PHASE:-0}" \
  --state-dir "${STATE_DIR:-.onex_state/session}" \
  ${DRY_RUN:+--dry-run} \
  ${SKIP_HEALTH:+--skip-health} \
  --output-json
```

Surface the JSON verbatim. On non-zero exit, report `status`, `halt_reason`, and blocking `health_report` dimensions — no prose fallback, no inline orchestration. If dispatch cannot execute, raise `SkillRoutingError` with the failing component.
