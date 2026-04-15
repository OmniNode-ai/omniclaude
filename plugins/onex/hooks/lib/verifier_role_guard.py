# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Verifier role guard — checks is_verifier field in agent YAML configs (OMN-8925).

Returns a verdict for a given agent_id by scanning the agents/configs directory.
Fail-safe: missing or unreadable YAML returns BLOCK, not PASS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

Verdict = Literal["PASS", "BLOCK"]


def check_agent_is_verifier(agent_id: str, agents_dir: Path) -> tuple[Verdict, str]:
    """Return (verdict, reason) for the given agent_id.

    PASS  — agent may dispatch Agent() calls
    BLOCK — agent is is_verifier=true or YAML not found (fail-safe)
    """
    if not agent_id:
        return "PASS", "no_agent_id"

    yaml_file: Path | None = agents_dir / f"{agent_id}.yaml"
    if not yaml_file.exists():
        yaml_file = _find_by_identity_name(agent_id, agents_dir)

    if yaml_file is None:
        return "BLOCK", "yaml_not_found"

    try:
        data = yaml.safe_load(yaml_file.read_text())
    except Exception:  # noqa: BLE001
        return "BLOCK", "yaml_parse_error"

    if not isinstance(data, dict):
        return "BLOCK", "invalid_yaml"

    if data.get("is_verifier", False):
        return "BLOCK", "is_verifier"

    return "PASS", "not_verifier"


def _find_by_identity_name(agent_id: str, agents_dir: Path) -> Path | None:
    """Search all YAMLs in agents_dir for agent_identity.name == agent_id."""
    for f in agents_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
            if isinstance(data, dict):
                identity = data.get("agent_identity", {})
                if isinstance(identity, dict) and identity.get("name") == agent_id:
                    return f
        except Exception:  # noqa: BLE001
            pass
    return None
