# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""E2E proof-of-life for dispatch claim registry (OMN-8931).

Simulates the 2026-04-15 cascade: 40 agents, same fix-containers prompt.
Verifies exactly 1 winner, 39 blocked, TTL expiry + reacquire.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

_lib_path = str(
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from dispatch_claim_gate import check_and_acquire

_PROMPT = "fix containers on 192.168.86.201"  # onex-allow-internal-ip
_SHORT_TTL = 2  # seconds — for TTL expiry test


@pytest.mark.e2e
def test_first_dispatch_acquires_claim(tmp_path: Path) -> None:
    result = check_and_acquire(_PROMPT, "agent-cascade-alpha", tmp_path)
    assert result["action"] == "acquired"
    blocker_id = str(result["blocker_id"])
    assert (tmp_path / f"{blocker_id}.json").exists(), (
        "Claim file must exist after acquire"
    )


@pytest.mark.e2e
def test_second_dispatch_blocked_with_evidence(tmp_path: Path) -> None:
    r1 = check_and_acquire(_PROMPT, "agent-cascade-alpha", tmp_path)
    assert r1["action"] == "acquired"
    blocker_id = str(r1["blocker_id"])

    r2 = check_and_acquire(_PROMPT, "agent-cascade-beta", tmp_path)
    assert r2["action"] == "blocked"
    assert r2["held_by"] == "agent-cascade-alpha"
    assert float(str(r2["ttl_remaining"])) > 0
    assert (tmp_path / f"{blocker_id}.json").exists(), (
        "Claim file must still exist after block"
    )


@pytest.mark.e2e
def test_cascade_simulation_40_agents_1_wins(tmp_path: Path) -> None:
    """Simulates the 2026-04-15 incident: 40 agents, exactly 1 wins."""
    results: list[dict[str, object]] = []

    def dispatch(agent_id: str) -> dict[str, object]:
        return check_and_acquire(_PROMPT, agent_id, tmp_path)

    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = [
            executor.submit(dispatch, f"agent-cascade-{i:02d}") for i in range(40)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    acquired = [r for r in results if r["action"] == "acquired"]
    blocked = [r for r in results if r["action"] == "blocked"]

    assert len(acquired) == 1, (
        f"Expected exactly 1 winner, got {len(acquired)}: {acquired}"
    )
    assert len(blocked) == 39, f"Expected 39 blocked, got {len(blocked)}"
    for b in blocked:
        assert "held_by" in b
        assert (
            float(str(b["ttl_remaining"])) >= 0
        )  # >=0: sub-ms race on 40-thread acquire


@pytest.mark.e2e
def test_after_ttl_second_agent_can_acquire(tmp_path: Path) -> None:
    r1 = check_and_acquire(
        _PROMPT, "agent-cascade-alpha", tmp_path, ttl_seconds=_SHORT_TTL
    )
    assert r1["action"] == "acquired"

    # Still blocked before TTL
    r_blocked = check_and_acquire(
        _PROMPT, "agent-cascade-beta", tmp_path, ttl_seconds=_SHORT_TTL
    )
    assert r_blocked["action"] == "blocked"

    # Wait for TTL to expire
    time.sleep(_SHORT_TTL + 0.5)

    r2 = check_and_acquire(
        _PROMPT, "agent-cascade-beta", tmp_path, ttl_seconds=_SHORT_TTL
    )
    assert r2["action"] == "acquired", f"Expected acquired after TTL, got {r2}"
    blocker_id = str(r2["blocker_id"])
    import json

    data = json.loads((tmp_path / f"{blocker_id}.json").read_text())
    assert data["claimant"] == "agent-cascade-beta"
