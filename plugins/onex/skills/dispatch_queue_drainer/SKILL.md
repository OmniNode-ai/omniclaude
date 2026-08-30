---
description: Drain the next QUEUED .onex_state/dispatch_queue YAML item through node_dispatch_worker and durably advance its lifecycle, without spawning agents or moving queue files. Dispatches to node_dispatch_queue_drainer (omnimarket).
mode: full
version: 2.0.0
level: advanced
debug: false
category: operations
tags:
  - dispatch-queue
  - operations
  - legacy
  - unblocking
author: OmniClaude Team
composable: true
args:
  - name: --queue-item-path
    description: "Path to a specific YAML queue item under .onex_state/dispatch_queue/. Omit to take the oldest item that is still QUEUED."
    required: false
  - name: --queue-dir
    description: "Queue directory to scan when --queue-item-path is omitted"
    required: false
  - name: --state-dir
    description: "State directory holding the lifecycle records and result artifacts"
    required: false
  - name: --claim-lease-seconds
    description: "Renewable claim lease; expiry marks the claim stale, never deletes the item (default: 900)"
    required: false
  - name: --dispatch-ack-timeout-seconds
    description: "How long a dispatched item may go unacknowledged before it is observably pending (default: 900)"
    required: false
  - name: --actor
    description: "Actor recorded on every lifecycle transition this run writes"
    required: false
  - name: --dry-run
    description: "Select, validate and compile the next QUEUED item but mutate nothing (default: false)"
    required: false
---

# Dispatch Queue Drainer

**Skill ID**: `onex:dispatch_queue_drainer`
**Version**: 2.0.0
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_dispatch_queue_drainer/`

---

## Purpose

Thin shim that dispatches to `node_dispatch_queue_drainer` in omnimarket. Takes the
next **QUEUED** legacy `.onex_state/dispatch_queue` YAML item, compiles it through
`node_dispatch_worker`, and durably advances that item through
`QUEUED → CLAIMED → DISPATCHED` (or `→ TERMINAL` with a typed stop reason). Use when
a dispatch queue is stuck and an operator needs to process items to unblock the
pipeline.

**The queue has a progress operator.** Selection skips any item an attempt already
holds or closed, so N successive invocations drain N distinct items, and a run that
compiles an item leaves it awaiting acknowledgement rather than counting it as
processed.

**Node invariants (enforced by handler, not this skill):**
- `first_slice_limit_is_one` — processes exactly one item per invocation; never batches
- `no_agent_or_taskcreate_spawn` — node does not spawn agents or call TaskCreate
- `no_queue_file_move_or_delete_by_default` — the item is transitioned by a durable
  append-only lifecycle record, never by moving or deleting the queue file
- `selection_skips_non_queued_items` — an item that is CLAIMED, DISPATCHED, STARTED
  or TERMINAL is never re-selected as if untouched
- `selected_item_is_durably_transitioned` — the selected item is provably moved off
  QUEUED before the run returns
- `dispatched_item_stays_pending_until_acknowledged` — a missing or timed-out
  acknowledgement leaves the item visibly PENDING, never counted as processed
- `claim_lease_expiry_marks_stale_never_deletes` — leases are renewable; expiry marks
  the claim stale and never deletes the item or silently returns it to QUEUED
- `unknown_terminal_reason_is_non_redispatchable` — an unclassifiable stop escalates
- `dry_run_mutates_nothing` — `--dry-run` writes no lifecycle record, no dispatch
  record and no result artifact, and never reaches the dispatch-worker boundary

The `first_slice_limit_is_one` invariant is a deliberate safety constraint. Operators
who need to drain multiple items invoke this skill once per item — which now works,
because each invocation advances the queue.

---

## Usage

```
/onex:dispatch_queue_drainer
/onex:dispatch_queue_drainer --dry-run
/onex:dispatch_queue_drainer --queue-item-path .onex_state/dispatch_queue/item-001.yaml
```

---

## Dispatch

```bash
onex skill dispatch_queue_drainer --dry-run
```

`onex skill dispatch_queue_drainer` resolves through the declarative
`skill_mapping.yaml` registry in omnibase_infra. The equivalent direct-node path
remains:

```bash
uv run onex run-node node_dispatch_queue_drainer --input '{"dry_run": true}'
```

The foreground must not process, move, or delete queue files inline. All selection,
compilation, lifecycle and dispatch logic is in the
node handler (`omnimarket/src/omnimarket/nodes/node_dispatch_queue_drainer/handlers/handler_dispatch_queue_drainer.py`).

---

## Output

The node returns `ModelDispatchQueueDrainerResult`. Surface the JSON output directly.

`status` describes what this **run** did; `lifecycle_phase` describes where the
**item** now is. They are deliberately separate: a `compiled` run leaves the item
`dispatched` and awaiting acknowledgement, which is not the same thing as processed.

Fields:
- `status`: `compiled | blocked | empty | dry_run`
- `queue_item_path`: path to the selected YAML file
- `lifecycle_phase`: `queued | claimed | dispatched | started | terminal` (null on
  `empty` and on `dry_run`, which transition nothing)
- `lifecycle_record_path`: path to the item's append-only lifecycle record
- `terminal_disposition`: `completed | stopped` when the item reached TERMINAL
- `terminal_reason`: `deliberate_cancellation | user_stop | session_quota |
  process_loss | dependency_failure | host_overload | timeout | unknown` — set only
  on a `stopped` disposition. `deliberate_cancellation` and `unknown` are
  **non-redispatchable by construction**; recovery policy keys off this value
- `result_artifact_path`: path to the written result artifact (empty on `dry_run`)
- `blocked_reason`: human-readable reason when `status == blocked`
- `dispatch_worker_command`: compiled worker command dict
- `dispatch_worker_result`: result from node_dispatch_worker if invoked
- `dry_run`: true when the run mutated nothing
- `processed_at`: ISO timestamp

**Backing node contract:** `omnimarket/src/omnimarket/nodes/node_dispatch_queue_drainer/contract.yaml`
**Focused test command (from contract):**
```bash
env -u PYTHONPATH uv run pytest tests/unit/nodes/node_dispatch_queue_drainer -v
```
