# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD-first test for OMN-8431: node_skill_overseer_verify_orchestrator removed from omniclaude.

Fails before removal, passes after.
"""

from __future__ import annotations

from pathlib import Path


def test_overseer_orchestrator_not_in_omniclaude() -> None:
    """After migration, omniclaude must NOT contain the orchestrator node.

    The node has been relocated to omnimarket per node consolidation policy.
    """
    src_root = Path(__file__).parent.parent.parent / "src" / "omniclaude" / "nodes"
    node_dir = src_root / "node_skill_overseer_verify_orchestrator"
    assert not node_dir.exists(), (
        "node_skill_overseer_verify_orchestrator still present in omniclaude — "
        "it should have been removed (relocated to omnimarket)"
    )
