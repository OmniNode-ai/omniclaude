---
description: Cofounder demo — fan out a curated task across multiple LLM paths (Gemini Flash, Claude Opus, Claude Sonnet, deterministic stub) and render an ASCII cost comparison chart. SCAFFOLDING ONLY — full fan-out lives in a follow-up PR.
mode: full
version: 0.1.0
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
    description: "Number of demo tasks to fan out (default: 3)"
    required: false
  - name: --prompts
    description: "Comma-separated override prompts. When omitted, the skill uses the 3 curated demo tasks."
    required: false
  - name: --dry-run
    description: "Run with canned responses instead of calling real LLMs. Also triggered by ONEX_DEMO_DRY_RUN=1."
    required: false
---

# /onex:demo — Cofounder Delegation Demo

> **Status: SCAFFOLDING ONLY.** This PR introduces the skill surface, argument
> schema, and dispatcher stub. The full fan-out implementation (multi-model
> handlers, cost compute node, ASCII renderer) lands in follow-up PRs against
> `omnibase_infra` and `omnimarket`. See **Deferred Scope** below.

**Announce at start:** "I'm using the demo skill to run the multi-model delegation fan-out."

## Overview

`/onex:demo delegation` is a cofounder-facing demonstration of the ONEX
delegation pipeline. It takes a small set of curated prompts and fans each one
out across four execution paths:

| Path | Model | Handler |
|------|-------|---------|
| Gemini Flash | `gemini/gemini-2.0-flash` | `HandlerLlmOpenaiCompatible` via OpenAI-compat endpoint |
| Claude Opus | `claude-opus-4-5` | `HandlerLlmCliClaude` via `claude -p --model ...` |
| Claude Sonnet | `claude-sonnet-4-6` | `HandlerLlmCliClaude` via `claude -p --model ...` |
| Deterministic stub | `onex-deterministic` | canned in-memory response (cost = $0) |

Per-path results flow through `node_demo_cost_compute` (pricing table × real
token counts) and `node_demo_renderer_effect` (ASCII bar chart). The entire
pipeline runs on `RuntimeLocal` + `EventBusInmemory` — no Docker, Kafka, or
Postgres required. Only `GEMINI_API_KEY` and a local `claude` binary are needed
for a live run.

## Usage

```
/onex:demo delegation
/onex:demo delegation --count 4
/onex:demo delegation --dry-run
ONEX_DEMO_DRY_RUN=1 /onex:demo delegation
```

## Dependencies

This skill depends on:

- `/onex:delegate` — the underlying single-path delegation skill that this demo
  fans out across. See `plugins/onex/skills/delegate/SKILL.md`.
- `HandlerLlmCliClaude` — new handler in `omnibase_infra` (Phase 1 of the plan).
- `node_demo_fanout_orchestrator`, `node_demo_cost_compute`,
  `node_demo_renderer_effect` — new nodes in `omnimarket` (Phases 2-4 of the
  plan).

Until those land, the dispatcher stub in this PR fails fast with a clear
message pointing at the follow-up work.

## Inputs

- **subcommand** *(required)*: Currently only `delegation`. Future subcommands
  (`routing`, `baseline`, `quality-gate`) are reserved.
- **--count N** *(optional)*: Number of curated tasks to fan out. Default `3`,
  max `4` (matching the plan's curated set).
- **--prompts** *(optional)*: Comma-separated user-supplied prompts that
  override the curated set.
- **--dry-run** *(optional)*: Run with pre-canned responses. Equivalent to
  `ONEX_DEMO_DRY_RUN=1`.

## Curated Tasks (Delegation Subcommand)

Default tasks when neither `--count` nor `--prompts` is supplied:

1. `test_generation` — `Write a pytest test for a function that adds two integers`
2. `model_routing` — `Which is cheaper: GPT-4o or Gemini Flash 2.0 for summarization tasks?`
3. `deterministic_skill` — `Run the ONEX skill router for ticket triage`

## Outputs

On a successful run the skill returns:

- Per-task, per-path classification + latency + token counts
- Cost breakdown per path (`cost_usd`, `tokens_input`, `tokens_output`,
  `tokens_estimated`)
- `cheapest_llm_model` (cheapest among LLM paths, excluding the deterministic
  stub)
- `cheapest_overall_path` (cheapest including deterministic)
- `savings_vs_opus_usd` per task
- ASCII bar chart rendered to stdout (via `node_demo_renderer_effect`)
- Aggregate timing summary

On scaffolding-only runs the skill returns a single error envelope pointing at
the follow-up tickets.

## Dispatcher Stub

This PR ships a fail-fast dispatcher. It validates `subcommand == "delegation"`,
checks for the presence of the downstream handler imports, and raises
`NotImplementedError` with a link to the plan if the full fan-out path is not
yet wired.

```python
#!/usr/bin/env python3
"""Dispatcher stub for /onex:demo delegation.

SCAFFOLDING ONLY — the real fan-out lives in follow-up PRs.
See docs/plans/2026-04-10-demo-skill-plan.md.
"""
from __future__ import annotations

import os
import sys
from typing import Any

PLAN_PATH = "docs/plans/2026-04-10-demo-skill-plan.md"
SCAFFOLD_MARKER = "demo-skill-scaffolding"


def dispatch(subcommand: str, **kwargs: Any) -> dict[str, Any]:
    """Fail-fast dispatcher stub for the /onex:demo skill.

    This stub exists to lock in the skill surface (args, outputs, docs) so the
    rest of the plan can land against a stable contract. The real fan-out is
    deferred — see the plan document referenced below.
    """
    if subcommand != "delegation":
        return {
            "success": False,
            "error": f"Unknown subcommand '{subcommand}'. Supported: delegation.",
            "scaffold_marker": SCAFFOLD_MARKER,
        }

    dry_run = kwargs.get("dry_run") or os.environ.get("ONEX_DEMO_DRY_RUN") == "1"

    try:
        # These imports intentionally live inside dispatch() so that import
        # errors surface as structured failures, not skill-load crashes.
        from omnimarket.nodes.node_demo_fanout_orchestrator.handlers import (  # type: ignore[import-not-found]
            HandlerDemoFanout,
        )
    except ImportError as exc:
        return {
            "success": False,
            "error": (
                "Demo fan-out handler is not yet implemented. This PR is "
                "scaffolding only — see the follow-up plan for the full "
                "implementation timeline."
            ),
            "missing_dependency": "omnimarket.nodes.node_demo_fanout_orchestrator",
            "import_error": repr(exc),
            "plan_path": PLAN_PATH,
            "scaffold_marker": SCAFFOLD_MARKER,
            "dry_run": dry_run,
        }

    # If we reach here, follow-up PRs have landed — real dispatch goes here.
    # Leaving a single NotImplementedError so that accidentally shipping this
    # stub into a wired environment fails loudly.
    raise NotImplementedError(
        "Full /onex:demo fan-out dispatch not yet implemented. "
        f"See {PLAN_PATH}."
    )


if __name__ == "__main__":
    argv = sys.argv[1:]
    sub = argv[0] if argv else "delegation"
    result = dispatch(sub)
    print(result)
    sys.exit(0 if result.get("success") else 1)
```

## Deferred Scope

The following work is intentionally **out of scope for this PR** and tracked in
`docs/plans/2026-04-10-demo-skill-plan.md`:

- **Phase 1 (omnibase_infra):** dict-access bug fix in
  `HandlerLlmCliSubprocess`, new `HandlerLlmCliClaude`, handlers `__init__.py`
  export.
- **Phase 2 (omnimarket):** `node_demo_cost_compute` COMPUTE node with pricing
  constants, input/output models, contract.yaml.
- **Phase 3 (omniclaude):** `render_ascii_bar_chart` helper in
  `plugins/onex/skills/_shared/status_formatter.py`.
- **Phase 4 (omnimarket + omniclaude):** `node_demo_fanout_orchestrator`,
  `node_demo_renderer_effect`, real dispatcher logic replacing the stub in
  this PR, env-key pre-flight, dry-run canned responses.
- **Phase 5:** integration test, node entry-point registration, smoke test.

## Truth Boundary

- This scaffolding does **not** prove the full fan-out works. It only proves
  the skill file parses, the args schema is stable, the dispatcher entry point
  is importable, and the test harness registers the skill directory.
- The dispatcher stub returns a structured failure envelope when its
  downstream dependencies are missing; it does not fall back to a mock path.
  A passing test does not imply a working demo.
- The `--dry-run` flag is documented here for the stable surface contract but
  the canned-response table is deferred to the follow-up PR.

## Related

- **Plan:** `docs/plans/2026-04-10-demo-skill-plan.md`
- **Sibling skill:** `plugins/onex/skills/delegate/SKILL.md`
- **Ticket:** demo-delegation-skill (P0, due Tue 2026-04-14)
