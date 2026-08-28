---
version: 2.0.0
description: "SCAFFOLD-ONLY. Contract inference (AST, no LLM) plus template scaffolding for ONEX nodes. The LLM business-logic fill stage does NOT exist; generated nodes need their handler bodies written by hand."
mode: full
level: advanced
debug: false
---

# Generate ONEX Node

> **Status: SCAFFOLD-ONLY.**
>
> Every version of this document before 2.0.0 advertised **"100% automated node generation"**, **"ZERO manual work"**, and a `BusinessLogicGenerator` that "writes working code". None of that was true, and none of it was ever true in this repo. This skill is documented here as what it provably is: **contract inference plus a template scaffold**. Handler bodies are written by hand, or by a delegation stage that has **not landed**.
>
> The overclaim mattered because it was load-bearing: other documents cited this skill as a working conversion pipeline. It is not one.

---

## What actually exists today

| Stage | Status | Where |
| -- | -- | -- |
| **Contract inference** — derive a `contract.yaml` draft from existing node source | **Live, AST-only, no LLM** | `omniintelligence/scripts/infer_contracts.py`, whose own module docstring reads: *"AST-only (no LLM calls). Scans Python files for classes inheriting from `Node*` base classes and generates contract.yaml drafts."* |
| **Template scaffold** — stamp a node package from templates | **Live** | `omnimarket/src/omnimarket/nodes/node_generate_node_effect/` |
| **LLM business-logic fill** — write the handler body | **DOES NOT EXIST *here*; live in omnimarket** | nothing in `omniclaude/src/` implements it. The omnimarket generation loop *does* fill bodies — see the live-run note below |
| **AI quorum / multi-model consensus validation** | **DOES NOT EXIST** | never ported; the `--enable-quorum` flag has no implementation behind it |
| **Registration** — the generated node is announced as an MCP tool | **Live, but not gated on the node working** | see below |

### What a live run actually produces (measured 2026-08-28, dev lane)

A real dispatch through omnimarket's `node_generation_consumer` was driven end-to-end on the dev lane and **succeeded**, so the honest account is more specific than "emits a shell":

- **A handler body IS generated.** The local model wrote correct, defensive Python for the requested task. This is not a stub.
- **But it is not a conforming ONEX handler.** The emitted body has the dict-in / dict-out shape `handle(input_data)`, not the canonical typed signature `handle(request: ModelX) -> ModelY`.
- **The emitted contract references models that were never generated.** It names an `input_model` / `output_model` module that no run creates, and omits `descriptor`, `handler_routing`, `node_version`, `inputs`/`outputs`, and `event_bus`.
- **Nothing is written to disk.** The contract and handler exist only as strings inside event payloads. There is no importable package.
- **Registration is not gated on the node working.** The run registered the node as an MCP tool, and *then* its only sandbox invocation failed.

**Net: a live run emits generated source text that is registered but not conforming, not staged, and not proven to run.** An earlier documented attempt failed outright — its response did not satisfy the accepted code-output contract and no code was staged or accepted. Treat "the loop works" as meaning *the dispatch path works*, not *the output is usable*.

---

## The documented entrypoint does not resolve

`skills/generate_node/generate` line 154 executes:

```bash
uv run omninode-generate "$prompt" "$@"
```

**There is no `omninode-generate` console script.** `omniclaude/pyproject.toml`'s `[project.scripts]` declares only `omniclaude-emit` and `omni-patterns`; the command is absent from the project venv's `bin/` and from `PATH`. The `generate` and `regenerate` wrappers in this directory are therefore **not runnable as written** — they fail at command resolution, after their prerequisite checks pass.

The components named in the old architecture diagram — `ContractInferencer`, `HybridStrategy`, `BusinessLogicGenerator` — have **no implementation in `omniclaude/src/`**. The only occurrence of those names in this repo is prose inside `src/omniclaude/nodes/node_skill_generate_node_orchestrator/contract.yaml`'s `description:` field. They were never ported from the archived predecessor repo.

---

## Where the working surface actually is

Node generation lives in **omnimarket**, not here, and is driven as a node dispatch rather than through this skill's wrapper scripts:

| Node | Role |
| -- | -- |
| `node_generation_consumer` | The dispatch entrypoint. Declares `runtime_dispatch.command_topic: onex.cmd.omnimarket.node-generation-requested.v1` with terminal success/failure events. |
| `node_generate_node_effect` | Template scaffold emission. |
| `node_generated_code_validator` | Validation of emitted code. |
| `node_generated_node_publish_effect` | Publication of the generated package. |
| `node_rsd_fill_compute` | A separate body-fill **seam**. Not the path a live dispatch takes — the fill measured above happens inside `node_generation_consumer` itself. |

For contract inference specifically, call the AST tool directly:

```bash
# from the root of an omniintelligence checkout
uv run python scripts/infer_contracts.py --dry-run
uv run python scripts/infer_contracts.py --node NodePatternStorageEffect --execute
```

---

## What you must still do by hand

After a scaffold run, expect to write:

- **The handler body.** This is the whole point of a node, and none of it is generated.
- **Contract I/O models** beyond what inference could derive from existing source. AST inference works from code that already exists; for a genuinely new node there is nothing to infer from.
- **Tests.** "Validation ensures quality" in the old text described a stage that does not write tests.

Budget this as writing a node with a pre-stamped skeleton — not as reviewing generated code.

---

## Prerequisites

The `generate` wrapper checks for a workspace-root env var, `uv`, and `OMNIBASE_INFRA_DB_URL` before it fails on the missing CLI. The infrastructure the old document listed (PostgreSQL, Kafka/Redpanda, Consul) is what the **omnimarket** generation loop needs; it is not what makes this skill's wrapper work, because nothing makes this skill's wrapper work.

`ZAI_API_KEY` / `ZAI_ENDPOINT` / `ZAI_MODEL` are read by the `regenerate` wrapper's prompt-extraction path, which likewise terminates at the same missing CLI.

---

## Honesty rule for this document

This skill sat in the **stubs-behind-complete-docs** failure class: a complete-looking document over a partial implementation. The rule going forward:

**No capability claim in this file without a citation to code that implements it, or to a receipt that proves it ran.** A percentage ("100% automated"), a duration ("10-25s per node"), or a quality score is a *measurement*; if no run produced it, it does not belong here. If the fill stage lands, this document changes in the same commit and cites the gate that proves it.

## See Also

- `omnimarket/src/omnimarket/nodes/node_generation_consumer/contract.yaml` — the real dispatch surface.
- `omniintelligence/scripts/infer_contracts.py` — the AST contract inferencer.
