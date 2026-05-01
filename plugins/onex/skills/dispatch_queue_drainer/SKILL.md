---
description: Drain one legacy .onex_state/dispatch_queue YAML item through node_dispatch_worker without spawning agents or moving queue files. Dispatches to node_dispatch_queue_drainer (omnimarket).
mode: full
version: 1.0.0
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
    description: "Path to the YAML queue item file under .onex_state/dispatch_queue/"
    required: true
  - name: --dry-run
    description: "Compile without dispatching (default: false)"
    required: false
---

# Dispatch Queue Drainer

**Skill ID**: `onex:dispatch_queue_drainer`
**Version**: 1.0.0
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_dispatch_queue_drainer/`
**Ticket**: OMN-9437

---

## Purpose

Thin shim that dispatches to `node_dispatch_queue_drainer` in omnimarket. Compiles
one legacy `.onex_state/dispatch_queue` YAML item through `node_dispatch_worker`
without spawning agents or moving queue files. Use when a dispatch queue is stuck
and an operator needs to manually process one item to unblock the pipeline.

**Node invariants (enforced by handler, not this skill):**
- `first_slice_limit_is_one` — processes exactly one item per invocation; never batches
- `no_agent_or_taskcreate_spawn` — node does not spawn agents or call TaskCreate
- `no_queue_file_move_or_delete_by_default` — queue files are not moved or deleted unless
  explicitly requested

The `first_slice_limit_is_one` invariant is a deliberate safety constraint. Operators
who need to drain multiple items must invoke this skill once per item. There is no
batch mode.

---

## Usage

```
/onex:dispatch_queue_drainer --queue-item-path .onex_state/dispatch_queue/item-001.yaml
/onex:dispatch_queue_drainer --queue-item-path .onex_state/dispatch_queue/item-001.yaml --dry-run
```

---

## Dispatch

```bash
uv run onex run-node node_dispatch_queue_drainer -- \
  --queue-item-path <queue_item_path> \
  ${DRY_RUN:+--dry-run}
```

Do not implement queue processing inline. All compilation and dispatch logic is in the
node handler (`omnimarket/src/omnimarket/nodes/node_dispatch_queue_drainer/handlers/handler_dispatch_queue_drainer.py`).

---

## Output

The node returns `ModelDispatchQueueDrainerResult`. Surface the JSON output directly.

Fields:
- `status`: `compiled | blocked | empty`
- `queue_item_path`: path to the processed YAML file
- `result_artifact_path`: path to the written result artifact (non-empty on success)
- `blocked_reason`: human-readable reason when `status == blocked`
- `dispatch_worker_command`: compiled worker command dict (non-null on `status == compiled`)
- `dispatch_worker_result`: result from node_dispatch_worker if invoked
- `processed_at`: ISO timestamp

**Backing node contract:** `omnimarket/src/omnimarket/nodes/node_dispatch_queue_drainer/contract.yaml`
**Focused test command (from contract):**
```bash
env -u PYTHONPATH uv run pytest tests/unit/nodes/node_dispatch_queue_drainer -v
```
