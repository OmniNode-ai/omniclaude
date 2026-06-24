---
description: Full post-release runtime redeploy — dispatches to node_redeploy_orchestrator (canonical ORCHESTRATOR; prod-gate COMPUTE + deploy publish-monitor EFFECT + FSM REDUCER over the bus)
mode: full
version: 4.0.0
level: advanced
debug: false
category: workflow
tags: [deploy, runtime, docker, infisical, post-release]
author: OmniClaude Team
composable: false
args:
  - name: --scope
    description: "Rebuild scope: full | runtime | core (default: full)"
    required: false
  - name: --git-ref
    description: "Git ref for deploy agent to pull (default: origin/main)"
    required: false
  - name: --versions
    description: "Plugin version pins JSON object: {\"pkg\": \"version\"}. Auto-detected if omitted."
    required: false
  - name: --skip-sync
    description: Skip SYNC_CLONES phase
    required: false
  - name: --verify-only
    description: Skip to VERIFY_HEALTH phase only
    required: false
  - name: --dry-run
    description: Print step commands without execution
    required: false
---

# Redeploy

**Announce at start:** "I'm using the redeploy skill."

## Usage

```
/redeploy
/redeploy --scope runtime
/redeploy --verify-only
/redeploy --dry-run
```

## Execution

Dispatch to `node_redeploy_orchestrator` — the canonical ORCHESTRATOR that owns phase sequencing and dispatches the prod-promotion gate (COMPUTE), the deploy-agent publish-monitor + rollback (EFFECT), and the FSM (REDUCER) over the bus. The shim performs a single dispatch and surfaces the node's terminal `ModelRedeployCompletedEvent` receipt.

```bash
onex run-node node_redeploy_orchestrator \
  --input '{"correlation_id": null, "scope": "full", "git_ref": "origin/main", "skip_sync": false, "verify_only": false, "dry_run": false}' \
  --timeout 660
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly; do not produce prose. All phase orchestration, retry logic, and circuit-breaker behavior live in the canonical node handlers, not in this shim.

## Architecture

```
SKILL.md     -> thin dispatch shim (this file)
orchestrator -> omnimarket/src/omnimarket/nodes/node_redeploy_orchestrator/   (ORCHESTRATOR; dispatches over the bus)
prod-gate    -> omnimarket/src/omnimarket/nodes/node_prod_promotion_gate_compute/  (COMPUTE; pure gate decision)
deploy       -> omnimarket/src/omnimarket/nodes/node_redeploy_deploy_effect/  (EFFECT; deploy-agent publish-monitor + rollback)
fsm          -> omnimarket/src/omnimarket/nodes/node_redeploy_fsm_reducer/    (REDUCER; phase transitions + circuit breaker)
handlers     -> each implements ProtocolMessageHandler.handle(envelope) -> ModelHandlerOutput
```

## Anti-Patterns

Two friction surfaces caused this skill to be misused — both produce
high-severity events in `.onex_state/friction/friction.ndjson`:

1. **`redeploy:tooling/manual-deploy-execution`** — never run `deploy-runtime.sh`,
   `docker compose up`, or any direct Docker / SSH command from the operator
   session. Dispatch to `node_redeploy` via the canonical invocation above.
   The node owns SSH-to-`INFRA_HOST`, Infisical seeding, and health verification;
   manual execution skips all three.
2. **`redeploy:tooling/deploy-targets-local-not-201`** — runtime containers live
   on `${INFRA_HOST}` (the default host runs on the LAN; see `~/.omnibase/.env`).
   The redeploy node SSHes to `INFRA_HOST` and runs Docker there. Never target
   `localhost` or local Docker from the redeploy skill or its callers — local
   Docker has no runtime containers and the deploy will silently no-op.

If the dispatched node is unavailable (e.g. omnimarket runtime offline), surface
the `SkillRoutingError` and stop. Do NOT fall through to inline `deploy-runtime.sh`
execution; that recreates the original friction.
