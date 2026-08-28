# Generate Node — Claude Code Skill

> **Status: SCAFFOLD-ONLY.**
> This file previously claimed "Fully automated ONEX node generation" and "100% automated node generation (contract + infrastructure + business logic)". Both were false. See `SKILL.md` for the corrected account and its citations.

## What this actually is

Contract inference (**AST-only, no LLM**) plus a template scaffold. The pipeline emits a **loadable, registered shell**; the LLM business-logic fill stage never landed. Handler bodies are written by hand.

The wrapper scripts in this directory (`generate`, `regenerate`) call `uv run omninode-generate`, and **no such console script exists** — it is absent from `omniclaude/pyproject.toml`'s `[project.scripts]`, from the project venv's `bin/`, and from `PATH`. They are not runnable as written.

## Where to go instead

| Need | Surface |
| -- | -- |
| Infer a `contract.yaml` from existing node source | `omniintelligence/scripts/infer_contracts.py` (AST-only) |
| Scaffold a node package | omnimarket's generation loop, dispatched at `node_generation_consumer` (`runtime_dispatch.command_topic: onex.cmd.omnimarket.node-generation-requested.v1`) |
| A filled handler body | nothing — write it yourself |

## Files

- `SKILL.md` — corrected skill documentation; read it before using anything here.
- `generate` — wrapper for a CLI that does not exist.
- `regenerate` — same, plus a Z.ai prompt-extraction path that terminates at the same missing CLI.
- `topics.yaml` — event topic declarations.

## Honesty rule

No capability claim in this directory without a citation to code that implements it, or to a receipt that proves it ran. Durations, percentages, and quality scores are measurements; if no run produced one, it does not belong in these docs.
