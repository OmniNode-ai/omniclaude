---
description: Bootstrap skill for contracts and seams first. From a design, list every node, crossing and crossing model; write the models and contracts; scaffold every node; wire the chain on the in-memory and Redpanda overlays; prove it connects; only then fill handlers. Replaced by its node-backed skill on node_contract_seams_orchestrator; replace it when that lands.
mode: full
version: 1.0.0
level: intermediate
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - seam
  - contracts
  - bootstrap
author: omninode
---

# Lean Contract Seams (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It runs nothing
for you: it puts the existing commands in the one order the operator ruled (about 2026-10-31T02:25Z):
"Start with contracts. Let's create seams for all the contracts and have everything
connects before we do anything else." It is replaced by its node-backed skill when that skill comes
online.

**Replaced by** the node-backed contract-seams skill on `node_contract_seams_orchestrator` (not built; it
would compose `node_generate_node_effect` for step 3, core's `node_contract_walker_check_compute` and event-chain
walker, `node_golden_chain_sweep` and `node_seam_reading_compute` for step 5). It has no ticket of its own yet.
**Replace this skill with the node-backed skill when that node lands.**

## The practice

A design is a graph before it is code: nodes, the crossings between them, and the typed models that
cross. Build the whole graph first, with every node returning a typed empty or INSUFFICIENT result,
and prove that an event travels from the first node to the last on every overlay. Defects found then
cost a contract edit. Defects found after the handlers are filled cost a rewrite, because each side
was built against its own idea of the seam.

## When to use

At the first build wave of any design that adds more than one node. When a plan says "contracts
first" or "seams first". When a later change wants a new contract: that is a design change, and it
starts again at step 1 (step 6).

Do not use it for a change inside one handler behind a seam that already connects.

## Steps by hand today

1. **List the graph from the design.** Read the design document itself, not a summary of it. Write
   three tables: every node with its archetype (orchestrator, compute, effect or reducer, nothing
   else); every crossing between two nodes, named by its topic (`onex.cmd.<owner>.<name>.v1` for a
   command, `onex.evt.<owner>.<name>.v1` for an event) or by its call; every typed model that crosses,
   one per crossing. A crossing with no model, or a node with no crossing, is a gap in the design: ask
   about it now, by one plain question, before writing anything.
2. **Write every model and every contract before any logic.** The models that cross a repository
   boundary go to omnibase_core (frozen Pydantic, `extra="forbid"`, enums for every closed set, with
   unit tests); node-local models stay in the node. Then write each node's `contract.yaml`: its
   archetype, its handler and input and output models, `event_bus` subscribe and publish topics, a
   typed `state_machine` with `state_machine_version` for every orchestrator and reducer (so the
   walker arms it), `protocol_dependencies` for every dependency (bus, clock, store, route, model,
   host, timeout, credential) with no literal value, and `runtime_dispatch.command_topic` or
   `externally_consumed_topics` where the graph meets the world. A value the design leaves open stays
   open in the contract and blocks evaluation; it is never guessed.
3. **Scaffold every node from its contract.** Use `onex:generate_node` for the package skeleton (it is
   scaffold-only; read its own status table first). Each handler returns a typed empty result or a
   typed INSUFFICIENT result with a reason code, and no business logic. Every dependency arrives
   through the constructor from DI; an in-memory implementation is only ever an injected default.
4. **Wire the chain and boot it on both overlays.** One chain test publishes the first event and reads
   the last, through the contracts only (handler, models and topics resolved by name from each
   `contract.yaml`). Run it on the in-memory overlay as a unit test, then on the Redpanda overlay as an
   integration test on a lab host through `/omni:lab-run`, with no code change between the two: only
   the overlay binds a different bus.
5. **Prove that it connects.** All three readings, each with its command and read time:
   - the event-chain walk over the new contracts with core's `ValidatorEventChainWalker`
     (`uv run python -m omnibase_core.nodes.node_validation_report_write_effect.runtime_validator_run
     omnibase_core.validation.validator_event_chain_walker:ValidatorEventChainWalker <node dirs>`,
     merged in omnibase_core#2165, released in 0.47.58): zero unconsumed topics, zero unproduced
     topics, zero states with no exit, zero undeclared triggers. Add core's contract walker report
     (`uv run python -m omnibase_core.nodes.node_contract_walker_check_compute.runtime_contract_walker_check`)
     for the orchestrator graph composed with the reducer FSM: every golden path reaches a terminal
     state;
   - `onex:golden_chain_sweep` over a chain registered for the new graph, from its head topic to its
     projection, fed the rows the chain test projected;
   - `onex:lean_seam_read` at each crossing: what crossed, compared with the model both sides
     declare, with zero mismatches and zero unreadable crossings.
   Plant one broken crossing (drop one subscription) and show that the walk refuses it, so the proof
   is not vacuous; then restore it.
6. **Only then fill the handlers.** Each later change fills a handler body behind a seam that already
   connects, and keeps the chain test, the walk and the seam reading green. A later change that adds a
   contract, a topic or a crossing model is a design change: it goes back to step 1, and the whole
   graph is proven again.

## Factory task per step

Each step above is replaced by this part of the node-backed skill.

| Step | Factory task |
| -- | -- |
| 1 | `node_contract_seams_orchestrator` design read (not built) |
| 2 | `node_contract_seams_orchestrator` contract and model emission (not built) |
| 3 | `node_generate_node_effect` (merged, scaffold only) |
| 4 | the chain test generated from the contracts (`node_event_chain_generator_compute`, merged) |
| 5 | `node_contract_walker_check_compute` (merged, core), `node_golden_chain_sweep` (merged), `node_seam_reading_compute` (merged; its skill is not built) |
| 6 | none: filling handlers is ordinary build work behind the proven seams |

## What this skill cannot do

It cannot decide a design question the document leaves open, and it cannot make the walk, the sweep
or the seam reading pass by editing a check. If a hook refuses a correct shape, fix the hook in its
home repository or report it; never add a baseline or a suppression to get past it.
