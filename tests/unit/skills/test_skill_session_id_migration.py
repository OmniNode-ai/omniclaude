# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify skill _lib files use resolve_session_id."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGETS = [
    "plugins/onex/skills/_lib/dod-evidence-runner/dod_evidence_runner.py",
    "plugins/onex/skills/env_sync_alert/_lib/check.py",
    "plugins/onex/skills/delegate/_lib/run.py",
    "plugins/onex/hooks/scripts/codex_cost_wrapper.py",
]


@pytest.mark.parametrize("rel_path", TARGETS)
def test_no_direct_legacy_env_reads(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text()
    forbidden = re.compile(
        r"""os\.(environ\.get|getenv)\(\s*["'](CLAUDE_SESSION_ID|ONEX_SESSION_ID|SESSION_ID)["']"""
    )
    assert not forbidden.search(text), f"Legacy read remains in {rel_path}"


@pytest.mark.parametrize("rel_path", TARGETS)
def test_uses_resolver(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text()
    assert "resolve_session_id" in text, f"{rel_path} must import resolver"
