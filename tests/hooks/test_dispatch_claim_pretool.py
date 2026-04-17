# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for dispatch_claim_gate.py extraction rules (OMN-8928)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_lib_path = str(
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from dispatch_claim_gate import check_and_acquire, extract_blocker_info


@pytest.mark.unit
def test_extract_ssh_201() -> None:
    info = extract_blocker_info(
        "ssh jonah@192.168.86.201 'docker ps'"  # onex-allow-internal-ip
    )
    assert info is not None
    kind, host, resource = info
    assert kind == "ssh_201"
    assert host == "192.168.86.201"  # onex-allow-internal-ip


@pytest.mark.unit
def test_extract_rpk_rebuild() -> None:
    info = extract_blocker_info(
        "rpk topic produce onex.cmd.deploy.rebuild-requested.v1 <<< '{}'"
    )
    assert info is not None
    kind, host, _ = info
    assert kind == "deploy_rebuild"


@pytest.mark.unit
def test_extract_fix_containers() -> None:
    info = extract_blocker_info(
        "fix containers on 192.168.86.201"  # onex-allow-internal-ip
    )
    assert info is not None
    kind, host, _ = info
    assert kind == "fix_containers"
    assert host == "192.168.86.201"  # onex-allow-internal-ip


@pytest.mark.unit
def test_extract_omn_ticket() -> None:
    info = extract_blocker_info("Implement OMN-8921 dispatch claim registry")
    assert info is not None
    kind, host, resource = info
    assert kind == "ticket_dispatch"
    assert "OMN-8921" in resource


@pytest.mark.unit
def test_extract_pr_merge() -> None:
    info = extract_blocker_info(
        "gh pr merge --repo OmniNode-ai/omniclaude 1322 --squash --auto"
    )
    assert info is not None
    kind, host, resource = info
    assert kind == "pr_merge"
    assert "omniclaude" in resource
    assert "1322" in resource


@pytest.mark.unit
def test_extract_explicit_blocker_id() -> None:
    sha1 = "a" * 40
    info = extract_blocker_info(f"blocker_id: {sha1}")
    assert info is not None
    kind, _, resource = info
    assert kind == "explicit"
    assert resource == sha1


@pytest.mark.unit
def test_no_match_returns_none() -> None:
    info = extract_blocker_info("ls -la /tmp")
    assert info is None


@pytest.mark.unit
def test_e2e_two_agents_same_prompt_first_acquired_second_blocked(
    tmp_path: Path,
) -> None:
    prompt = "fix containers on 192.168.86.201"  # onex-allow-internal-ip
    result1 = check_and_acquire(prompt, "agent-alpha", tmp_path)
    result2 = check_and_acquire(prompt, "agent-beta", tmp_path)

    assert result1["action"] == "acquired"
    assert result2["action"] == "blocked"
    assert "held_by" in result2
    assert result2["held_by"] == "agent-alpha"
    assert "ttl_remaining" in result2
