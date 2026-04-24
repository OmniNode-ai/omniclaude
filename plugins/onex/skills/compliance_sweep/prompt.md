# /onex:compliance_sweep — dispatch-only shim

Dispatch to `node_compliance_sweep` in omnimarket. Do not reimplement scans inline.

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `--repos <comma-list>` | all handler repos |
| `--checks <comma-list>` | all checks |
| `--dry-run` | unset |

## Dispatch

```bash
cd "$ONEX_REGISTRY_ROOT/omnimarket"  # local-path-ok: canonical omnimarket worktree
uv run onex run node_compliance_sweep -- \
  ${REPOS:+--repos "$REPOS"} \
  ${CHECKS:+--checks "$CHECKS"} \
  ${DRY_RUN:+--dry-run}
```

Surface the JSON verbatim. On non-zero exit, report `status`, violation counts, and top `by_type` — no prose fallback, no inline scanning. If dispatch cannot execute, raise `SkillRoutingError` with the failing component.
