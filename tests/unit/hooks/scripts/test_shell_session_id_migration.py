# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify shell hook scripts use CLAUDE_CODE_SESSION_ID."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
TARGETS = [
    "plugins/onex/hooks/pre_tool_use_convention_injector.sh",
    "plugins/onex/hooks/scripts/pre_tool_use_pipeline_gate.sh",
    "plugins/onex/hooks/scripts/pre_tool_use_dod_completion_guard.sh",
    "plugins/onex/hooks/scripts/post-tool-use-quality.sh",
    "plugins/onex/hooks/scripts/post_tool_use_team_observability.sh",
]


@pytest.mark.parametrize("rel_path", TARGETS)
def test_no_legacy_env_var_reads(rel_path: str) -> None:
    """Shell scripts must read CLAUDE_CODE_SESSION_ID, not legacy aliases."""
    text = (REPO_ROOT / rel_path).read_text()
    # Match ${CLAUDE_SESSION_ID...} or ${ONEX_SESSION_ID...} or bare $CLAUDE_SESSION_ID/$ONEX_SESSION_ID
    # SESSION_ID is a valid local variable name in shell scripts, so only block the named aliases.
    forbidden = re.compile(r"\$\{?\b(CLAUDE_SESSION_ID|ONEX_SESSION_ID)\b")
    matches = forbidden.findall(text)
    assert not matches, f"Legacy env-var read remains in {rel_path}: {matches}"


@pytest.mark.parametrize("rel_path", TARGETS)
def test_references_canonical_var(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text()
    assert "CLAUDE_CODE_SESSION_ID" in text, (
        f"{rel_path} must reference CLAUDE_CODE_SESSION_ID"
    )
