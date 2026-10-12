# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dispatch claim release — PostToolUse claim teardown (OMN-8929).

Uses dispatch_claim_gate.py's extraction (including its overlay-supplied claim
hosts) to find the claim file and release it if owned by the current claimant.
No dep on onex_change_control or omnibase_core, so the hook venv needs no extra
packages.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from dispatch_claim_gate import extract_blocker_info

# One extraction rule set for acquire and release: the gate's, so the claim file
# a release looks for is the one the gate wrote.


def _compute_blocker_id(kind: str, host: str, resource: str) -> str:
    import hashlib

    return hashlib.sha1(
        f"{kind}|{host}|{resource}".encode(), usedforsecurity=False
    ).hexdigest()


def release_claim(
    tool_input: str,
    claimant: str,
    claims_dir: Path,
    hosts: Sequence[str] | None = None,
) -> dict[str, object]:
    """Release a claim held by claimant for the given tool_input.

    Returns:
      {"action": "no_match"}         — no extraction rule matched
      {"action": "not_found"}        — no claim file exists (already expired/released)
      {"action": "not_owner"}        — claim exists but owned by another agent
      {"action": "released", "blocker_id": X}  — successfully released
    """
    info = extract_blocker_info(tool_input, hosts)
    if info is None:
        return {"action": "no_match"}

    kind, host, resource = info

    if kind == "explicit":
        blocker_id = resource
    else:
        blocker_id = _compute_blocker_id(kind, host, resource)

    p = claims_dir / f"{blocker_id}.json"
    if not p.exists():
        return {"action": "not_found", "blocker_id": blocker_id}

    try:
        data: dict[str, object] = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        p.unlink(missing_ok=True)
        return {"action": "released", "blocker_id": blocker_id}

    held_by = str(data.get("claimant", ""))
    if held_by != claimant:
        return {"action": "not_owner", "blocker_id": blocker_id, "held_by": held_by}

    p.unlink(missing_ok=True)
    return {"action": "released", "blocker_id": blocker_id}


if __name__ == "__main__":
    # CLI smoke test: python3 dispatch_claim_release.py smoke <claims_dir>
    import hashlib as _hashlib

    if len(sys.argv) >= 3 and sys.argv[1] == "smoke":
        d = Path(sys.argv[2])
        d.mkdir(parents=True, exist_ok=True)
        import datetime

        bid = _hashlib.sha1(
            b"ticket_dispatch|local|OMN-8929",
            usedforsecurity=False,
        ).hexdigest()
        claim = {
            "blocker_id": bid,
            "kind": "ticket_dispatch",
            "host": "local",
            "resource": "OMN-8929",
            "claimant": "agent-alpha",
            "claimed_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
            "ttl_seconds": 300,
            "tool_name": "Agent",
        }
        (d / f"{bid}.json").write_text(json.dumps(claim))

        r1 = release_claim("dispatch OMN-8929 smoke", "agent-beta", d)
        assert r1["action"] == "not_owner", f"Expected not_owner, got {r1}"

        r2 = release_claim("dispatch OMN-8929 smoke", "agent-alpha", d)
        assert r2["action"] == "released", f"Expected released, got {r2}"
        assert not (d / f"{bid}.json").exists(), "Claim file should be deleted"

        r3 = release_claim("dispatch OMN-8929 smoke", "agent-alpha", d)
        assert r3["action"] == "not_found", f"Expected not_found, got {r3}"

        import json as _json

        print(_json.dumps({"r1": r1, "r2": r2, "r3": r3}, indent=2))
        print("SMOKE TEST PASSED")
