# Generate Node — Claude Code Skill

> **Status: SCAFFOLD-ONLY.**
> This file previously claimed "Fully automated ONEX node generation" and "100% automated node generation (contract + infrastructure + business logic)". Both were false. See `SKILL.md` for the corrected account and its citations.

## What this actually is

Contract inference (**AST-only, no LLM**) plus a template scaffold. **Nothing in this repo fills handler bodies.** omnimarket's generation loop does generate bodies on a live dispatch (measured 2026-08-28), but the output is non-canonical, references models it never emits, is never written to disk, and is registered without being proven to run — so it is not a substitute for writing the node. See `SKILL.md` for the measured readback.

The wrapper scripts in this directory (`generate`, `regenerate`) call `uv run omninode-generate`, and **no such console script exists** — it is absent from `omniclaude/pyproject.toml`'s `[project.scripts]`, from the project venv's `bin/`, and from `PATH`. They are not runnable as written.

## Where to go instead

| Need | Surface |
| -- | -- |
| Infer a `contract.yaml` from existing node source | `omniintelligence/scripts/infer_contracts.py` (AST-only) |
| Scaffold a node package | omnimarket's generation loop, dispatched at `node_generation_consumer` (`runtime_dispatch.command_topic: onex.cmd.omnimarket.node-generation-requested.v1`) |
| A handler body you can actually ship | nothing — write it yourself. The generation loop emits one, but not in canonical shape and not to disk |

## Files

- `SKILL.md` — corrected skill documentation; read it before using anything here.
- `generate` — wrapper for a CLI that does not exist.
- `regenerate` — same, plus a Z.ai prompt-extraction path that terminates at the same missing CLI.
- `topics.yaml` — event topic declarations.

## Honesty rule

No capability claim in this directory without a citation to code that implements it, or to a receipt that proves it ran. Durations, percentages, and quality scores are measurements; if no run produced one, it does not belong in these docs.
