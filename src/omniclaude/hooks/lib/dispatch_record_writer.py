# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Writer + reader for dispatch-scoped state (OMN-9084).

``write_dispatch_record`` persists a :class:`ModelDispatchRecord` as YAML at
``$ONEX_STATE_DIR/dispatches/<agent-id>.yaml``; the directory is created if
missing. ``read_tool_call_jsonl`` iterates the append-only JSONL written by
``post_tool_use_subagent_tool_log.sh`` for the same agent.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from omniclaude.hooks.lib.onex_state import ensure_state_dir, state_path
from omniclaude.hooks.model_dispatch_record import ModelDispatchRecord


def write_dispatch_record(record: ModelDispatchRecord) -> Path:
    """Persist *record* under ``$ONEX_STATE_DIR/dispatches/`` and return its path."""
    dispatches_dir = ensure_state_dir("dispatches")
    out_path = dispatches_dir / f"{record.agent_id}.yaml"
    payload = record.model_dump(mode="json")
    out_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return out_path


def read_tool_call_jsonl(agent_id: str) -> Iterator[dict[str, Any]]:
    """Yield one parsed dict per non-empty line of the subagent tool-calls log."""
    jsonl_path = state_path("dispatches", agent_id, "tool-calls.jsonl")
    if not jsonl_path.is_file():
        return
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            yield json.loads(stripped)
