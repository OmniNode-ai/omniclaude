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
| **Loadability / registration** — the emitted package loads and registers | **Live** | proven on structure only |
| **LLM business-logic fill** — write the handler body | **DOES NOT EXIST** | no implementation anywhere in `omniclaude/src/` |
| **AI quorum / multi-model consensus validation** | **DOES NOT EXIST** | never ported; the `--enable-quorum` flag has no implementation behind it |

**Net: the pipeline emits a loadable, registered shell.** It does not emit working business logic, and it never has. The single end-to-end attempt on record did not satisfy the accepted code-output contract; normalization retries failed closed and no generated code was staged or accepted.

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
| `node_rsd_fill_compute` | The body-fill **seam** — not a landed end-to-end fill stage. |

For contract inference specifically, call the AST tool directly:

```bash
cd "$OMNI_HOME/omniintelligence"
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

The `generate` wrapper checks for `$OMNI_HOME`, `uv`, and `OMNIBASE_INFRA_DB_URL` before it fails on the missing CLI. The infrastructure the old document listed (PostgreSQL, Kafka/Redpanda, Consul) is what the **omnimarket** generation loop needs; it is not what makes this skill's wrapper work, because nothing makes this skill's wrapper work.

`ZAI_API_KEY` / `ZAI_ENDPOINT` / `ZAI_MODEL` are read by the `regenerate` wrapper's prompt-extraction path, which likewise terminates at the same missing CLI.

---

## Honesty rule for this document

This skill sat in the **stubs-behind-complete-docs** failure class: a complete-looking document over a partial implementation. The rule going forward:

**No capability claim in this file without a citation to code that implements it, or to a receipt that proves it ran.** A percentage ("100% automated"), a duration ("10-25s per node"), or a quality score is a *measurement*; if no run produced it, it does not belong here. If the fill stage lands, this document changes in the same commit and cites the gate that proves it.

## See Also

- `omnimarket/src/omnimarket/nodes/node_generation_consumer/contract.yaml` — the real dispatch surface.
- `omniintelligence/scripts/infer_contracts.py` — the AST contract inferencer.
