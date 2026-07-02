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

The real `onex` CLI has no `--mode/--phase/--state-dir/--output-json` flags — those
values are fields on `ModelSessionOrchestratorCommand` (see
`omnimarket/src/omnimarket/nodes/node_session_orchestrator/handlers/handler_session_orchestrator.py`)
and must be passed as a JSON **envelope**, not CLI flags. Build the envelope from
the parsed `$ARGUMENTS`, write it to a file, then dispatch:

```bash
cd "$OMNI_HOME/omnimarket"  # canonical registry clone — never a bare worktree path

cat > /tmp/session-envelope.json <<EOF
{
  "mode": "${MODE:-interactive}",
  "phase": ${PHASE:-0},
  "dry_run": ${DRY_RUN:-false},
  "skip_health": ${SKIP_HEALTH:-false},
  "standing_orders_path": "${STANDING_ORDERS:-.onex_state/session/standing_orders.json}",
  "state_dir": "${STATE_DIR:-.onex_state/session}"
}
EOF

# Canonical (Kafka required):
uv run onex run-node node_session_orchestrator --input "$(cat /tmp/session-envelope.json)"

# Local fallback (no Kafka — use when the broker is unreachable):
uv run onex node node_session_orchestrator --input /tmp/session-envelope.json --output receipt
```

`onex run-node --input` takes the JSON payload inline as a string; `onex node`/`onex run
--input` takes a path to a JSON **file** — do not swap the two forms.

Surface the JSON verbatim. On non-zero exit, report `status`, `halt_reason`, and blocking `health_report` dimensions — no prose fallback, no inline orchestration. If dispatch cannot execute, raise `SkillRoutingError` with the failing component.
