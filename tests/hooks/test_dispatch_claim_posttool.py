# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for dispatch_claim_release.py (OMN-8929)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_lib_path = str(
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from dispatch_claim_release import extract_blocker_info, release_claim


def _write_claim(claims_dir: Path, blocker_id: str, claimant: str) -> None:
    claim = {
        "blocker_id": blocker_id,
        "kind": "fix_containers",
        "host": "192.168.86.201",  # onex-allow-internal-ip
        "resource": "docker_containers",
        "claimant": claimant,
        "claimed_at": datetime.now(tz=UTC).isoformat(),
        "ttl_seconds": 300,
        "tool_name": "Agent",
    }
    (claims_dir / f"{blocker_id}.json").write_text(json.dumps(claim))


@pytest.mark.unit
def test_release_no_match_returns_no_match(tmp_path: Path) -> None:
    result = release_claim("ls -la /tmp", "agent-alpha", tmp_path)
    assert result["action"] == "no_match"


@pytest.mark.unit
def test_release_not_found_when_no_claim_file(tmp_path: Path) -> None:
    result = release_claim(
        "fix containers on 192.168.86.201",  # onex-allow-internal-ip
        "agent-alpha",
        tmp_path,
    )
    assert result["action"] == "not_found"
    assert "blocker_id" in result


@pytest.mark.unit
def test_release_not_owner_when_different_claimant(tmp_path: Path) -> None:
    info = extract_blocker_info(
        "fix containers on 192.168.86.201"  # onex-allow-internal-ip
    )
    assert info is not None
    import hashlib

    kind, host, resource = info
    bid = hashlib.sha1(
        f"{kind}|{host}|{resource}".encode(), usedforsecurity=False
    ).hexdigest()
    _write_claim(tmp_path, bid, "agent-alpha")

    result = release_claim(
        "fix containers on 192.168.86.201",  # onex-allow-internal-ip
        "agent-beta",
        tmp_path,
    )
    assert result["action"] == "not_owner"
    assert result["held_by"] == "agent-alpha"
    assert (tmp_path / f"{bid}.json").exists(), "Claim must NOT be deleted by non-owner"


@pytest.mark.unit
def test_release_owner_deletes_claim_file(tmp_path: Path) -> None:
    info = extract_blocker_info(
        "fix containers on 192.168.86.201"  # onex-allow-internal-ip
    )
    assert info is not None
    import hashlib

    kind, host, resource = info
    bid = hashlib.sha1(
        f"{kind}|{host}|{resource}".encode(), usedforsecurity=False
    ).hexdigest()
    _write_claim(tmp_path, bid, "agent-alpha")

    result = release_claim(
        "fix containers on 192.168.86.201",  # onex-allow-internal-ip
        "agent-alpha",
        tmp_path,
    )
    assert result["action"] == "released"
    assert result["blocker_id"] == bid
    assert not (tmp_path / f"{bid}.json").exists(), "Claim file must be deleted"


@pytest.mark.unit
def test_release_after_release_returns_not_found(tmp_path: Path) -> None:
    info = extract_blocker_info(
        "fix containers on 192.168.86.201"  # onex-allow-internal-ip
    )
    assert info is not None
    import hashlib

    kind, host, resource = info
    bid = hashlib.sha1(
        f"{kind}|{host}|{resource}".encode(), usedforsecurity=False
    ).hexdigest()
    _write_claim(tmp_path, bid, "agent-alpha")

    r1 = release_claim(
        "fix containers on 192.168.86.201",  # onex-allow-internal-ip
        "agent-alpha",
        tmp_path,
    )
    r2 = release_claim(
        "fix containers on 192.168.86.201",  # onex-allow-internal-ip
        "agent-alpha",
        tmp_path,
    )
    assert r1["action"] == "released"
    assert r2["action"] == "not_found"


@pytest.mark.unit
def test_extract_ssh_201() -> None:
    info = extract_blocker_info(
        "ssh jonah@192.168.86.201 'docker ps'"  # onex-allow-internal-ip
    )
    assert info is not None
    kind, host, _ = info
    assert kind == "ssh_201"
    assert host == "192.168.86.201"  # onex-allow-internal-ip


@pytest.mark.unit
def test_extract_omn_ticket() -> None:
    info = extract_blocker_info("Implement OMN-8929 posttool release hook")
    assert info is not None
    kind, _, resource = info
    assert kind == "ticket_dispatch"
    assert "OMN-8929" in resource


@pytest.mark.unit
def test_e2e_acquire_then_release_then_reacquire(tmp_path: Path) -> None:
    """Full lifecycle: pretool acquires, posttool releases, next agent can acquire."""
    sys.path.insert(0, _lib_path)
    from dispatch_claim_gate import check_and_acquire

    prompt = "fix containers on 192.168.86.201"  # onex-allow-internal-ip

    r1 = check_and_acquire(prompt, "agent-alpha", tmp_path)
    assert r1["action"] == "acquired"

    r_blocked = check_and_acquire(prompt, "agent-beta", tmp_path)
    assert r_blocked["action"] == "blocked"

    r_release = release_claim(prompt, "agent-alpha", tmp_path)
    assert r_release["action"] == "released"

    r2 = check_and_acquire(prompt, "agent-beta", tmp_path)
    assert r2["action"] == "acquired"
