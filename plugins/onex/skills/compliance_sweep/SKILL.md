---
description: "Dispatch-only shim for handler contract compliance sweep. All scanning (topic-compliance, transport-compliance, handler-routing, logic-in-node) executes in node_compliance_sweep (omnimarket). The skill parses --repos/--checks/--dry-run and dispatches; no inline scanning."
version: 3.0.0
mode: full
level: advanced
debug: false
category: verification
tags: [compliance, contracts, handlers, shim, dispatch-only, thin-shim]
author: OmniClaude Team
composable: false
args:
  - name: --repos
    description: "Comma-separated repo names (default: all handler repos)"
    required: false
  - name: --checks
    description: "Comma-separated check IDs: topic-compliance,transport-compliance,handler-routing,logic-in-node (default: all)"
    required: false
  - name: --dry-run
    description: "Scan and report only — no ticket creation (default: false)"
    required: false
inputs:
  - name: repos
    description: "list[str] — repos to scan; empty = all"
outputs:
  - name: status
    description: "compliant | violations_found | error"
  - name: total_violations
    description: "Integer count of violations across scanned repos"
  - name: by_type
    description: "Violation counts grouped by check type (see node_compliance_sweep contract for the enum)"
---

# /onex:compliance_sweep — dispatch-only shim

**Skill ID**: `onex:compliance_sweep` · **Backing node**: `omnimarket/src/omnimarket/nodes/node_compliance_sweep/` · **Ticket**: OMN-8754

## Routing Contract

- **Classification**: Deterministic
- **Dispatch**: see `prompt.md` — single invocation against `node_compliance_sweep` from the omnimarket worktree
- **No inline scanning**: all compliance checks live in the handler, not this skill
- **No prose fallback**: on dispatch failure, raise `SkillRoutingError` — do not produce prose

See `prompt.md` for the exact dispatch invocation.
