---
description: Run OmniClaude bus health audit (Layer 2 domain validation)
mode: full
version: "1.0.0"
level: advanced
debug: false
category: diagnostics
tags:
  - diagnostics
  - kafka
  - event-bus
author: omninode
composable: true
args:
  - name: --json
    description: "Output results in JSON format for dashboard integration"
    required: false
  - name: --failures-only
    description: "Show only failed checks"
    required: false
  - name: --verbose
    description: "Include sample payloads for failed checks"
    required: false
  - name: --skip-daemon
    description: "Skip emit daemon health check"
    required: false
  - name: --broker
    description: "Override Kafka broker address (default: reads $KAFKA_BOOTSTRAP_SERVERS)"
    required: false
  - name: --sample-count
    description: "Number of messages to sample per topic (default: 20)"
    required: false
---

<!-- routing-enforced: dispatches to node_bus_audit_compute. Dispatch path is correctly wired. Handler raises NotImplementedError (node_not_implemented: true in contract.yaml) pending OMN-8760 implementation. When OMN-8760 lands, remove this comment. -->

# Bus Audit

**Usage:** `/bus-audit [flags]`

Dispatch to `node_bus_audit_compute` in omnimarket. Do not reimplement bus audit logic inline.

## Announce

Say: "I'm using the bus-audit skill to dispatch node_bus_audit_compute."

## Dispatch

```bash
onex run node_bus_audit_compute -- \
  ${JSON:+--json} \
  ${FAILURES_ONLY:+--failures-only} \
  ${VERBOSE:+--verbose} \
  ${SKIP_DAEMON:+--skip-daemon} \
  ${BROKER:+--broker "$BROKER"} \
  ${SAMPLE_COUNT:+--sample-count "$SAMPLE_COUNT"}
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement bus audit logic inline. If the node is unavailable, stop — do not fall back to inline script execution or prose audit.
