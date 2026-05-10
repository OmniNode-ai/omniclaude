# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify plugins/onex/hooks/lib/ files route through resolve_session_id."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

LIB_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
TARGETS = [
    "team_lead_foreground_guard.py",
    "correlation_trace_emitter.py",
    "agent_status_emitter.py",
    "auth_gate_adapter.py",
    "pipeline_slack_notifier.py",
    "cost_accounting.py",
]


@pytest.mark.parametrize("name", TARGETS)
def test_no_direct_env_reads(name: str) -> None:
    text = (LIB_ROOT / name).read_text()
    forbidden = re.compile(
        r"""os\.(environ\.get|getenv)\(\s*["'](CLAUDE_SESSION_ID|ONEX_SESSION_ID|SESSION_ID|CLAUDE_CODE_SESSION_ID)["']"""
    )
    assert not forbidden.search(text), (
        f"{name} must use resolve_session_id, not direct env reads"
    )


@pytest.mark.parametrize("name", TARGETS)
def test_imports_resolve_session_id(name: str) -> None:
    text = (LIB_ROOT / name).read_text()
    assert "resolve_session_id" in text, f"{name} must import resolve_session_id"


def test_team_lead_guard_constant_renamed() -> None:
    text = (LIB_ROOT / "team_lead_foreground_guard.py").read_text()
    assert 'ENV_SESSION_ID = "CLAUDE_SESSION_ID"' not in text
