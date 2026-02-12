---
name: checkpoint
description: Pipeline checkpoint management for resume, replay, and phase validation
version: 1.0.0
category: infrastructure
tags:
  - checkpoint
  - pipeline
  - resume
  - replay
  - state
author: OmniClaude Team
args:
  - name: operation
    description: "Operation: write | read | validate | list"
    required: true
  - name: --ticket-id
    description: "Ticket identifier (e.g., OMN-2144)"
    required: true
  - name: --run-id
    description: "Pipeline run UUID (required for write, read, and validate; optional for list)"
    required: false  # conditionally required -- see description
  - name: --phase
    description: "Pipeline phase: implement | local_review | create_pr | pr_release_ready | ready_for_merge"
    required: false
  - name: --attempt
    description: "Attempt number (default: 1)"
    required: false
  - name: --repo-commit-map
    description: "JSON object mapping repo names to commit SHAs"
    required: false
  - name: --artifact-paths
    description: "JSON array of relative artifact paths"
    required: false
  - name: --payload
    description: "JSON object with phase-specific payload fields"
    required: false
---

# Checkpoint

## Overview

Checkpoints record the successful completion of each pipeline phase. They are written after a phase finishes (never during) and enable:

- **Resume**: Restart a pipeline from a specific phase without re-running prior phases
- **Validation**: Verify that prior phase outputs are structurally sound before skipping
- **Replay**: Audit trail of pipeline execution across attempts
- **Idempotency**: Append-only writes with monotonically increasing attempt numbers

Checkpoints are backed by the `omnibase_infra` checkpoint node infrastructure (OMN-2143) and managed through the `checkpoint_manager.py` CLI wrapper.

**Announce at start:** "I'm using the checkpoint skill to manage pipeline state."

## Storage Layout

Checkpoints are stored as YAML files under the user's home directory:

```
~/.claude/checkpoints/{ticket_id}/{run_id}/phase_{N}_{name}_a{attempt}.yaml
```

Where:
- `{ticket_id}` -- Linear ticket identifier (e.g., `OMN-2144`)
- `{run_id}` -- Pipeline run UUID
- `{N}` -- Phase ordinal (1-5)
- `{name}` -- Phase value string
- `{attempt}` -- Monotonically increasing attempt counter

Example:
```
~/.claude/checkpoints/OMN-2144/a1b2c3d4/phase_1_implement_a1.yaml
~/.claude/checkpoints/OMN-2144/a1b2c3d4/phase_2_local_review_a1.yaml
~/.claude/checkpoints/OMN-2144/a1b2c3d4/phase_2_local_review_a2.yaml  # retry
~/.claude/checkpoints/OMN-2144/a1b2c3d4/phase_3_create_pr_a1.yaml
```

Writes are append-only: existing checkpoint files are never modified or overwritten.

## Checkpoint Contract

Each checkpoint YAML file contains these fields:

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Forward-compatibility version (currently `"1.0.0"`) |
| `run_id` | UUID | Pipeline run correlation ID |
| `ticket_id` | string | Linear ticket identifier |
| `phase` | enum | Pipeline phase that completed |
| `timestamp_utc` | datetime | UTC timestamp of phase completion (explicitly injected) |
| `repo_commit_map` | dict[str, str] | Mapping of repo name to commit SHA |
| `artifact_paths` | tuple[str, ...] | Relative paths of output artifacts |
| `attempt_number` | int (>=1) | Monotonically increasing attempt counter |
| `phase_payload` | union | Phase-specific payload (discriminated on `phase` field) |

### Phase Ordinals

| Phase | Ordinal | Value |
|-------|---------|-------|
| Implement | 1 | `implement` |
| Local Review | 2 | `local_review` |
| Create PR | 3 | `create_pr` |
| PR Release Ready | 4 | `pr_release_ready` |
| Ready for Merge | 5 | `ready_for_merge` |

## Per-Phase Payload Reference

### implement

| Field | Type | Description |
|-------|------|-------------|
| `phase` | literal `"implement"` | Discriminator |
| `branch_name` | string | Git branch name created |
| `commit_sha` | string (7-40 hex) | HEAD commit SHA after implementation |
| `files_changed` | tuple[str, ...] | Relative paths of changed files |

### local_review

| Field | Type | Description |
|-------|------|-------------|
| `phase` | literal `"local_review"` | Discriminator |
| `iteration_count` | int (>=1) | Number of review-fix iterations |
| `issue_fingerprints` | tuple[str, ...] | Fingerprints of issues found and resolved |
| `last_clean_sha` | string (7-40 hex) | Commit SHA of the last clean state |

### create_pr

| Field | Type | Description |
|-------|------|-------------|
| `phase` | literal `"create_pr"` | Discriminator |
| `pr_url` | string | Full URL of the created PR |
| `pr_number` | int (>=1) | PR number on the remote |
| `head_sha` | string (7-40 hex) | HEAD SHA pushed to the remote |

### pr_release_ready

| Field | Type | Description |
|-------|------|-------------|
| `phase` | literal `"pr_release_ready"` | Discriminator |
| `last_review_sha` | string (7-40 hex) | Commit SHA of the last review pass |
| `issue_fingerprints` | tuple[str, ...] | Issues found and resolved |

### ready_for_merge

| Field | Type | Description |
|-------|------|-------------|
| `phase` | literal `"ready_for_merge"` | Discriminator |
| `label_applied_at` | datetime | UTC timestamp when the merge-ready label was applied |

## CLI Usage

All operations use `checkpoint_manager.py` located at `${CLAUDE_PLUGIN_ROOT}/hooks/lib/checkpoint_manager.py`.

### Write a Checkpoint

```bash
python ${CLAUDE_PLUGIN_ROOT}/hooks/lib/checkpoint_manager.py write \
  --ticket-id OMN-2144 \
  --run-id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --phase implement \
  --attempt 1 \
  --repo-commit-map '{"omniclaude": "a1b2c3d"}' \
  --artifact-paths '["src/foo.py", "tests/test_foo.py"]' \
  --payload '{"branch_name": "feat/OMN-2144", "commit_sha": "a1b2c3d", "files_changed": ["src/foo.py"]}'
```

Output:
```json
{
  "success": true,
  "checkpoint_path": "OMN-2144/a1b2c3d4.../phase_1_implement_a1.yaml",
  "correlation_id": "..."
}
```

### Read Latest Checkpoint

```bash
python ${CLAUDE_PLUGIN_ROOT}/hooks/lib/checkpoint_manager.py read \
  --ticket-id OMN-2144 \
  --run-id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --phase implement
```

Output:
```json
{
  "success": true,
  "correlation_id": "...",
  "checkpoint": { ... }
}
```

### Validate a Checkpoint

Reads the checkpoint and then performs structural validation (schema version, path normalization, commit SHA format, phase-payload agreement, timestamp sanity).

```bash
python ${CLAUDE_PLUGIN_ROOT}/hooks/lib/checkpoint_manager.py validate \
  --ticket-id OMN-2144 \
  --run-id a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --phase implement
```

Output:
```json
{
  "is_valid": true,
  "success": true,
  "errors": [],
  "warnings": [],
  "correlation_id": "...",
  "checkpoint": { ... }
}
```

### List All Checkpoints

```bash
# All checkpoints for a ticket
python ${CLAUDE_PLUGIN_ROOT}/hooks/lib/checkpoint_manager.py list \
  --ticket-id OMN-2144

# Scoped to a specific run
python ${CLAUDE_PLUGIN_ROOT}/hooks/lib/checkpoint_manager.py list \
  --ticket-id OMN-2144 \
  --run-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Output:
```json
{
  "success": true,
  "count": 3,
  "checkpoints": [ ... ],
  "correlation_id": "..."
}
```

## Integration with ticket-pipeline

The `ticket-pipeline` skill writes checkpoints after each phase completes and validates them during `--skip-to` resume. See `plugins/onex/skills/ticket-pipeline/prompt.md` for the integration details.

## Error Handling

- **omnibase_infra not installed**: CLI prints JSON error and exits with code 1
- **Invalid phase name**: CLI prints JSON error with valid phase list
- **Checkpoint already exists**: Handler raises error (increment attempt_number)
- **Path traversal**: Handler rejects ticket IDs that escape the checkpoint root
- **Absolute artifact paths**: Rejected by both CLI and handler validation
- **Corrupt YAML files**: Skipped during list, reported during read

All checkpoint operations in the pipeline context are non-blocking -- write failures log a warning but do not stop the pipeline.

## See Also

- `ticket-pipeline` skill (writes checkpoints after each phase)
- `local-review` skill (writes checkpoints after each iteration when `--checkpoint` is provided)
- `omnibase_infra` checkpoint nodes (OMN-2143: infrastructure implementation)
