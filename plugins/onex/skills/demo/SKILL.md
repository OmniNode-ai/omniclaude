---
description: Cofounder demo — fan out curated delegation tasks across Gemini Flash, Claude Opus, Claude Sonnet, and the deterministic ONEX path, then render an ASCII cost comparison chart through native OmniMarket nodes.
mode: full
version: 0.2.0
level: advanced
debug: true
category: demo
tags:
  - demo
  - delegation
  - fan-out
  - cost-comparison
  - multi-model
author: omninode
args:
  - name: subcommand
    description: "Demo subcommand. Currently only 'delegation' is supported."
    required: true
  - name: --count
    description: "Number of curated demo tasks to fan out (default: 3)"
    required: false
  - name: --prompts
    description: "Comma-separated override prompts. When omitted, the skill uses the curated demo tasks."
    required: false
  - name: --dry-run
    description: "Run with deterministic provider fixtures while still dispatching through native OmniMarket nodes."
    required: false
---

# /onex:demo — Cofounder Delegation Demo

**Announce at start:** "I'm using the demo skill to run the multi-model delegation fan-out."

## Runtime Boundary

`/onex:demo delegation` dispatches through the OmniMarket runtime adapter and the native demo node contracts:

- `node_demo_fanout_orchestrator`
- `node_demo_cost_compute`
- `node_demo_renderer_effect`

The skill shim must not import node handlers directly and must not synthesize a successful response outside the runtime path. Dry-run uses deterministic provider fixtures as fan-out inputs, but the fan-out, cost aggregation, and rendering still run through the native node contracts and local runtime/event-bus boundary.

## Usage

```bash
/onex:demo delegation
/onex:demo delegation --count 2
/onex:demo delegation --dry-run
ONEX_DEMO_DRY_RUN=1 /onex:demo delegation
```

## Curated Tasks

Default tasks when neither `--count` nor `--prompts` is supplied:

1. `Write a pytest test for a function that adds two integers`
2. `Which is cheaper: GPT-4o or Gemini Flash 2.0 for summarization tasks?`
3. `Run the ONEX skill router for ticket triage`

## Outputs

Successful runs return:

- per-task, per-model inference results
- per-model cost breakdown
- `cheapest_llm_model`
- `cheapest_overall_path`
- ASCII chart lines rendered by `node_demo_renderer_effect`
- native node list and run/correlation IDs

## Live Provider Guard

Dry-run is the deterministic, zero-spend proof path. Live mode is explicit and the fan-out node performs provider preflight before any live call. Missing `GEMINI_API_KEY` or missing local `claude` CLI must surface as a structured runtime failure, not an import crash or hidden fallback.
