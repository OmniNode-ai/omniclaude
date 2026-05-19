---
description: Multi-model adversarial code review (Gemini, Codex, Qwen3-Coder, DeepSeek-R1, Claude) with weighted-union finding aggregation and iterative convergence. Cannot rubber-stamp. Use --static for static-analysis-only mode (dead code, missing error handling, stubs, Kafka wiring, schema mismatches, hardcoded values, missing tests).
mode: full
version: 6.0.0
level: intermediate
debug: false
category: review
tags:
  - review
  - adversarial
  - pr
  - plan
  - multi-model
  - quality
  - risk
  - convergence
  - static-analysis
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: pr
    description: PR number to review (mutually exclusive with --file).
    required: false
  - name: repo
    description: Target GitHub repo (e.g., OmniNode-ai/omniclaude). Required with --pr.
    required: false
  - name: file
    description: "Path to a plan file to review (mutually exclusive with --pr). Alias: --plan-path."
    required: false
  - name: plan-path
    description: "Alias for --file: path to a plan or design document to review adversarially"
    required: false
  - name: ticket_id
    description: Linear ticket ID for loading TCB constraints
    required: false
  - name: models
    description: "Comma-separated model list (default codex,deepseek-r1)."
    required: false
  - name: passes
    description: "Fixed number of passes to run. Default: iterates until 2 consecutive clean passes."
    required: false
  - name: gate
    description: "Gate mode: structured pass/fail/block verdict suitable for merge gating."
    required: false
  - name: gate-only
    description: "Review-only gate mode (no fix-apply). Safe to invoke from sub-agent context."
    required: false
  - name: strict
    description: "In --gate mode: block on MINOR+ findings (default blocks on MAJOR+)"
    required: false
  - name: static
    description: "Static-analysis-only mode: 7 code quality checks without adversarial review."
    required: false
  - name: repos
    description: "Comma-separated repo names to scan in --static mode"
    required: false
  - name: categories
    description: "Comma-separated finding categories for --static mode"
    required: false
  - name: dry-run
    description: "In --static mode: scan and report only, no tickets created."
    required: false
  - name: ticket
    description: "In --static mode: create Linear tickets for findings"
    required: false
  - name: max-tickets
    description: "In --static mode: hard cap on tickets created per run (default: 10)"
    required: false
---

# /onex:hostile_reviewer — Multi-Model Adversarial Review

**Skill ID**: `onex:hostile_reviewer`
**Version**: 6.0.0
**Backing node**: `node_hostile_reviewer`

## Changelog

- **6.0.0** — Re-enabled (OMN-7981). Contract-driven model routing: endpoints declared in contract.yaml model_routing, resolved from env vars at runtime. N-1 graceful degradation when endpoints are down.
- **5.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_hostile_reviewer`.
- **4.0.0** — Added DISABLED notice (OMN-10111).

## What this skill does

Dispatches through `onex run-node node_hostile_reviewer`. The node owns multi-model
review dispatch (Codex, DeepSeek-R1, Qwen3-Coder), finding aggregation, convergence
loop, and artifact persistence. This shim contains no inline review logic.

**Announce at start:** "I'm using the hostile-reviewer skill."

## Dispatch

**PR mode:**
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "pr": <pr_number>,
  "repo": "<owner/repo>",
  "models": ["codex", "deepseek-r1"],
  "passes": null,
  "gate": false,
  "gate_only": false,
  "strict": false
}' 2>/dev/null
```

**File mode:**
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "file": "<path>",
  "models": ["codex", "deepseek-r1"],
  "passes": null
}' 2>/dev/null
```

**Static mode:**
```bash
uv run onex run-node node_hostile_reviewer --input '{
  "static": true,
  "repos": null,
  "categories": null,
  "dry_run": false,
  "ticket": false,
  "max_tickets": 10
}' 2>/dev/null
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

**`2>/dev/null` is MANDATORY** on all invocations — models emit thousands of tokens of
chain-of-thought to stderr; silencing it keeps context windows viable.

## Wire Schema

Contract target: `node_hostile_reviewer`

Command topic: `onex.cmd.omnimarket.hostile-reviewer-start.v1`

Terminal events:
- `onex.evt.omnimarket.hostile-reviewer-phase-transition.v1`
- `onex.evt.omnimarket.hostile-reviewer-completed.v1`
