---
description: One-dispatch runtime closeout — dispatches to node_runtime_closeout_orchestrator (canonical ORCHESTRATOR; preflight + fresh-deploy fitness gate + deploy reuse + runtime proof matrix over the bus, terminal ModelCloseoutReceipt)
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
skill_kind: methodology
tags: [closeout, deploy, runtime, proof-matrix, post-release]
author: OmniClaude Team
composable: false
args:
  - name: --lane
    description: "Target runtime lane: dev | stability | prod (default: dev). Prod stays operator-gated."
    required: false
  - name: --promote
    description: "Operator intent to promote the proven artifact down the lane ladder. Prod promotion stays operator-gated downstream."
    required: false
  - name: --proof-set
    description: "Runtime proof matrix slice: required | full (default: required)"
    required: false
---

<!-- routing-enforced: dispatches to node_runtime_closeout_orchestrator. -->

# Runtime Closeout

**Announce at start:** "I'm using the runtime-closeout skill."

**Skill ID**: `onex:runtime_closeout`
**Version**: 1.0.0
**Owner**: omniclaude
**Epic**: <TICKET>

## Usage

```
/runtime-closeout
/runtime-closeout --lane dev
/runtime-closeout --lane stability --proof-set full
/runtime-closeout --lane prod --promote          # prod stays operator-gated
```

## Execution

Dispatch to `node_runtime_closeout_orchestrator` — the canonical ORCHESTRATOR
that owns the closeout phase sequencing and dispatches every phase OVER THE BUS.
The shim performs a single dispatch and surfaces the node's terminal
`ModelCloseoutReceipt`. All phase orchestration lives in the node handlers, not
in this shim.

```bash
onex run-node node_runtime_closeout_orchestrator \
  --input '{"correlation_id": null, "runtime_lane": "dev", "proof_set": "required", "promote": false}' \
  --timeout 900
```

`--lane stability` maps to `runtime_lane: "stability-test"`; `--lane prod` maps
to `runtime_lane: "prod"`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it
directly; do not produce prose.

## Phases (bus-native FSM)

The orchestrator walks these phases by consuming each phase's completion fact off
the bus — it never runs an in-process loop:

1. **PREFLIGHT** — read-only identity / broker / projection / migration /
   rollback inspection. Never mutates the lane. A failing preflight completes
   `BLOCKED` before any deploy.
2. **FITNESS_GATE** — the fresh-deploy fitness gate (<TICKET> sibling). A
   drifted artifact is rejected `BLOCKED` before any lane mutation.
3. **DEPLOY** — reuses `node_redeploy_orchestrator` (the `redeploy-start`
   command). Prod promotion stays operator-gated by the redeploy orchestrator's
   own prod-promotion gate — this skill never relaxes it.
4. **PROOF_MATRIX** — reuses `node_golden_chain_sweep` + `node_integration_sweep`.
   Cells (delegation / sea / gate_zero / context / savings / cross_feature) are
   classified `required` | `stretch` | `research`; each is proven with a fresh
   CID → typed terminal → projection readback. `--proof-set required` proves only
   the required cells; `--proof-set full` proves the whole matrix.
5. **RECEIPT** — the terminal `closeout-completed` event carries
   `ModelCloseoutReceipt`: SHA / image table, migration ledger, per-cell
   verdicts, rollback plan, residual risk, and the rolled-up recommendation
   (`customer_beta` | `internal_integration` | `hold`).

## Architecture

```
SKILL.md     -> thin dispatch shim (this file)
orchestrator -> omnimarket/src/omnimarket/nodes/node_runtime_closeout_orchestrator/  (ORCHESTRATOR; dispatches over the bus)
deploy       -> omnimarket/src/omnimarket/nodes/node_redeploy_orchestrator/          (REUSED for the deploy phase)
proof-matrix -> omnimarket/src/omnimarket/nodes/node_golden_chain_sweep/             (REUSED for runtime proof)
             -> omnimarket/src/omnimarket/nodes/node_integration_sweep_orchestrator/ (REUSED for runtime proof)
receipt      -> omnimarket/src/omnimarket/events/runtime_closeout.py::ModelCloseoutReceipt
```

## Anti-Patterns

- Never run `deploy-runtime.sh`, `docker compose up`, or any direct Docker / SSH
  command from the operator session. The deploy phase dispatches to
  `node_redeploy_orchestrator`, which owns SSH-to-runtime, Infisical seeding, and
  health verification.
- Never relax the prod-promotion gate. `--promote --lane prod` still routes the
  deploy through `node_redeploy_orchestrator`'s prod-promotion gate, which
  requires a fresh operator-approved grant. An agent cannot self-promote prod.

If the dispatched node is unavailable, surface the `SkillRoutingError` and stop.
Do NOT fall through to inline deploy execution.
