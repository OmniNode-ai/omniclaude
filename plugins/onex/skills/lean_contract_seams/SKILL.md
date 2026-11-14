---
description: Thin dispatch shim for contracts and seams first. Builds the node_contract_seams_orchestrator run request from a design (nodes, crossings, head, tail) and starts it through onex run-node. The node writes every contract, scaffolds every node, matches every crossing, walks and drives the chain and sweeps the golden chain; its reducer says whether the design is connected, refused or failed. No orchestration logic here.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: process
skill_kind: methodology
backing_node: node_contract_seams_orchestrator
tags:
  - lean
  - seam
  - contracts
  - dispatch-only
author: omninode
inputs:
  - name: design
    description: "ModelContractSeamsDesign: design_id, nodes, crossings, head, tail"
outputs:
  - name: run_result
    description: "ModelContractSeamsRunResult JSON: final_state, transitions, seam_verdicts, walk_issues, chain_event_types, refused_by, failure"
---

# Lean Contract Seams

**Backing node**: `node_contract_seams_orchestrator` (omnimarket), with its reducer
`node_contract_seams_reducer`, which owns the run's state machine.

The operator ruled (about 2026-10-31T02:25Z): "Start with contracts. Let's create seams for all
the contracts and have everything connects before we do anything else." This skill is the dispatch
shim for that practice. It replaced the hand-run bootstrap form of the same name; the node now
runs every step the bootstrap listed.

## What the node does

One run walks the orchestrator's execution graph over one design, in this order, and folds each
step into the reducer:

| Step | Node it runs | Reducer state on pass |
| -- | -- | -- |
| emit_contracts | the orchestrator's own emit operation | `contracts_written` |
| scaffold_nodes | `node_generate_node_effect`, with the written contract | `scaffolded` |
| read_seam_graph, match_seams | `node_seam_graph_compute`, `node_seam_match_compute` | `seams_matched` |
| walk_event_chain, gate_chains | core's contract walker, the chain drive on the bus, `node_event_chain_generator_compute` | `chains_generated` |
| sweep_golden_chain | `node_golden_chain_sweep` | `golden_chain_passed` |
| confirm_connected | the drive's tail event | `connected` |

A step that does not pass moves the run to `refused` and names the step (`refused_by`); a step
that raises moves it to `failed` and names the cause (`failure`). A mismatched crossing is refused
at `match_seams` with the field that differs (`seam_verdicts[].mismatching_field_path`).

## When to use

At the first build wave of any design that adds more than one node, and whenever a later change
adds a contract, a topic or a crossing model: that is a design change, and the whole graph is
proven again. Do not use it for a change inside one handler behind a seam that already connects.

## Run it

1. **Write the design.** Read the design document itself and write its graph as a
   `ModelContractSeamsDesign`: every node with its archetype and one-line description, every
   crossing with its topic, producer, consumer and what each side declares crosses
   (`envelope_model`, `envelope_version`, `key_fields`), the head command and the tail event. A
   crossing with no model or a node with no crossing is a gap: ask about it by one plain question
   before running anything, or the node refuses the design at `emit_contracts`.
2. **Start the node.** `output_root` is an empty absolute directory on the runtime's host:

   ```bash
   onex run-node node_contract_seams_orchestrator --timeout 120 --input '{
     "correlation_id": "<uuid>",
     "output_root": "<empty absolute directory>",
     "design": <the design as JSON>
   }'
   ```

3. **Read the result.** `final_state` is `connected`, `refused` or `failed`. Report it with
   `refused_by` or `failure`, the seam verdicts and the chain the drive saw. Fix a refusal in the
   design, never in a check, and run again into a fresh `output_root`.
4. **Only then fill the handlers.** Each later change fills a handler body behind a seam that
   already connects and keeps the run `connected`.

## What this skill cannot do

It cannot decide a design question the document leaves open, and it cannot make a step pass by
editing a check. If a hook refuses a correct shape, fix the hook in its home repository or report
it; never add a baseline or a suppression to get past it.
