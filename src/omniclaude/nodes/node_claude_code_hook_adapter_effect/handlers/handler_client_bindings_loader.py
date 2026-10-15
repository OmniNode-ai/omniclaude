# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read the client_bindings.claude_code section out of the adapter contract (OMN-18531)."""

from __future__ import annotations

from pathlib import Path

import yaml

from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientSection,
)

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contract.yaml"


def load_client_section(contract_path: Path = CONTRACT_PATH) -> ModelClientSection:
    """The section as a typed model; an absent section is an empty one."""
    raw = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    section = (raw.get("client_bindings") or {}).get("claude_code") or {}
    return ModelClientSection.model_validate(section)
