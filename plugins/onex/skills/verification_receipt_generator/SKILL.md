---
description: Use when a task completion claim needs independent CI or test evidence via node_verification_receipt_generator (omnimarket)
mode: full
version: 1.0.1
level: intermediate
debug: false
category: verification
tags:
  - verification
  - verification-results
  - ci
  - dod
author: OmniClaude Team
composable: true
args:
  - name: --task-id
    description: "Task identifier"
    required: true
  - name: --claim
    description: "What the task claims to have done (quoted string)"
    required: true
  - name: --repo
    description: "Exact GitHub OWNER/REPO identity (e.g. OmniNode-ai/omniclaude); required whenever CI verification or a PR number is requested"
    required: false
  - name: --pr
    description: "PR number to verify CI checks for"
    required: false
  - name: --worktree-path
    description: "Path to worktree for pytest verification"
    required: false
  - name: --run-tests
    description: "Run pytest in worktree (default: true)"
    required: false
  - name: --dry-run
    description: "Return a dry-run result without running verification"
    required: false
---

# Verification Receipt Generator

**Skill ID**: `onex:verification_receipt_generator`
**Version**: 1.0.1
**Owner**: omniclaude
**Backing node**: `omnimarket/src/omnimarket/nodes/node_verification_receipt_generator/`
---

## Purpose

Thin shim that dispatches to `node_verification_receipt_generator` in omnimarket.
Checks task completion claims against CI and test evidence. Kills rubber-stamping:
the node probes `gh pr checks` and/or runs `pytest` in the worktree and returns
structured per-dimension verification evidence.

---

## Usage

`--repo` must be the exact `OWNER/REPO` identity whenever `--pr` is supplied or
CI verification is requested. Bare slugs such as `omniclaude` and duplicated
slugs such as `OmniNode-ai/omniclaude/omniclaude` are rejected by the backing
request model.

```text
# CI only
/verification-receipt-generator --task-id TASK-ID --claim "CI checks pass on PR #567" --pr 567 --repo OmniNode-ai/omniclaude

# Tests only; replace the path with an existing ticket worktree
/verification-receipt-generator --task-id TASK-ID --claim "focused tests pass" --worktree-path /path/to/ticket-worktree --run-tests

# Dry run
/verification-receipt-generator --task-id TASK-ID --claim "preview verification request" --dry-run
```

---

## Dispatch

Dispatch exactly one valid JSON object for the selected mode.

CI only (`worktree_path` is empty and local tests are disabled):

```json
{"task_id":"TASK-ID","claim":"CI checks pass on PR #567","repo":"OmniNode-ai/omniclaude","pr_number":567,"worktree_path":"","verify_ci":true,"verify_tests":false,"dry_run":false}
```

Tests only (`repo` and `pr_number` are JSON null; use an existing worktree):

```json
{"task_id":"TASK-ID","claim":"focused tests pass","repo":null,"pr_number":null,"worktree_path":"/path/to/ticket-worktree","verify_ci":false,"verify_tests":true,"dry_run":false}
```

Dry run (no verification backend executes):

```json
{"task_id":"TASK-ID","claim":"preview verification request","repo":null,"pr_number":null,"worktree_path":"","verify_ci":false,"verify_tests":false,"dry_run":true}
```

Pass the selected object as `INPUT_JSON`:

```bash
uv run onex run-node node_verification_receipt_generator --input "${INPUT_JSON}"
```

The skill only selects and dispatches the typed input. Do not implement
verification logic inline; all CI, pytest, and dry-run behavior remains in the
backing node handler.

---

## Output

The node returns `ModelVerificationReceipt`:

- `task_id: str` — task whose completion claim was checked
- `claim: str` — claim submitted for verification
- `overall_pass: bool` — true only if ALL checks passed
- `checks: list` — per-dimension evidence (CI checks, pytest results)
- `verified_at: str` — ISO timestamp
- `verifier: str` — backing node identity

Surface the JSON output. If `overall_pass == false`, render which checks failed.

**Backing node contract:** `omnimarket/src/omnimarket/nodes/node_verification_receipt_generator/contract.yaml`
