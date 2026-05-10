# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify src/omniclaude stragglers route through resolve_session_id."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/omniclaude/nodes/node_agent_chat/handler_auto_emit.py",
        "src/omniclaude/lib/utils/quality_enforcer.py",
        "src/omniclaude/lib/core/agent_router.py",
    ],
)
def test_no_legacy_env_var_reads(rel_path: str) -> None:
    """Legacy env-var names must not be read directly from the listed source files."""
    text = (REPO_ROOT / rel_path).read_text()
    # Match os.environ.get / os.getenv on legacy names (any quoting style)
    forbidden = re.compile(
        r"""os\.(environ\.get|getenv)\(\s*["'](CLAUDE_SESSION_ID|ONEX_SESSION_ID|SESSION_ID)["']"""
    )
    matches = forbidden.findall(text)
    assert not matches, f"Legacy env-var read remains in {rel_path}: {matches}"


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/omniclaude/nodes/node_agent_chat/handler_auto_emit.py",
        "src/omniclaude/lib/utils/quality_enforcer.py",
        "src/omniclaude/lib/core/agent_router.py",
    ],
)
def test_imports_resolve_session_id(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text()
    assert "resolve_session_id" in text, (
        f"{rel_path} must import and use resolve_session_id"
    )
