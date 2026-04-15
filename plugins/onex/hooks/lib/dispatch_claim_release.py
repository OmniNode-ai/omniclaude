# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dispatch claim release — PostToolUse claim teardown (OMN-8929).

Mirrors dispatch_claim_gate.py extraction logic to find the claim file
and release it if owned by the current claimant. All logic is inlined
(no dep on onex_change_control or omnibase_core) so the hook venv needs
no extra packages.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Same pattern constants as dispatch_claim_gate.py (must stay in sync)
_RE_EXPLICIT = re.compile(r"blocker_id:\s*([0-9a-f]{40})", re.IGNORECASE)
_RE_SSH_201 = re.compile(r"ssh\s+\S*192\.168\.86\.201", re.IGNORECASE)
_RE_RPK_REBUILD = re.compile(r"rpk\s+topic\s+produce\s+\S*rebuild", re.IGNORECASE)
_RE_FIX_CONTAINERS = re.compile(
    r"fix.{0,20}containers\s+on\s+192\.168\.86\.201", re.IGNORECASE
)
_RE_OMN_TICKET = re.compile(r"\bOMN-(\d{4,6})\b")
_RE_PR_MERGE = re.compile(
    r"gh\s+pr\s+merge\s+.*?--repo\s+OmniNode-ai/([^\s]+)\s+(\d+)", re.IGNORECASE
)


def extract_blocker_info(tool_input: str) -> tuple[str, str, str] | None:
    """Extract (kind, host, resource) — identical to dispatch_claim_gate."""
    if _RE_EXPLICIT.search(tool_input):
        m = _RE_EXPLICIT.search(tool_input)
        assert m is not None
        return ("explicit", "local", m.group(1))

    if _RE_SSH_201.search(tool_input):
        return (
            "ssh_201",
            "192.168.86.201",  # onex-allow-internal-ip
            "ssh_session",
        )

    if _RE_RPK_REBUILD.search(tool_input):
        return (
            "deploy_rebuild",
            "192.168.86.201",  # onex-allow-internal-ip
            "rebuild_request",
        )

    if _RE_FIX_CONTAINERS.search(tool_input):
        return (
            "fix_containers",
            "192.168.86.201",  # onex-allow-internal-ip
            "docker_containers",
        )

    m = _RE_OMN_TICKET.search(tool_input)
    if m:
        return ("ticket_dispatch", "local", f"OMN-{m.group(1)}")

    m = _RE_PR_MERGE.search(tool_input)
    if m:
        return ("pr_merge", "github.com", f"OmniNode-ai/{m.group(1)}#{m.group(2)}")

    return None


def _compute_blocker_id(kind: str, host: str, resource: str) -> str:
    import hashlib

    return hashlib.sha1(
        f"{kind}|{host}|{resource}".encode(), usedforsecurity=False
    ).hexdigest()


def release_claim(
    tool_input: str,
    claimant: str,
    claims_dir: Path,
) -> dict[str, object]:
    """Release a claim held by claimant for the given tool_input.

    Returns:
      {"action": "no_match"}         — no extraction rule matched
      {"action": "not_found"}        — no claim file exists (already expired/released)
      {"action": "not_owner"}        — claim exists but owned by another agent
      {"action": "released", "blocker_id": X}  — successfully released
    """
    info = extract_blocker_info(tool_input)
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
            b"fix_containers|192.168.86.201|docker_containers",  # onex-allow-internal-ip
            usedforsecurity=False,
        ).hexdigest()
        claim = {
            "blocker_id": bid,
            "kind": "fix_containers",
            "host": "192.168.86.201",  # onex-allow-internal-ip
            "resource": "docker_containers",
            "claimant": "agent-alpha",
            "claimed_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
            "ttl_seconds": 300,
            "tool_name": "Agent",
        }
        (d / f"{bid}.json").write_text(json.dumps(claim))

        r1 = release_claim(
            "fix containers on 192.168.86.201",  # onex-allow-internal-ip
            "agent-beta",
            d,
        )
        assert r1["action"] == "not_owner", f"Expected not_owner, got {r1}"

        r2 = release_claim(
            "fix containers on 192.168.86.201",  # onex-allow-internal-ip
            "agent-alpha",
            d,
        )
        assert r2["action"] == "released", f"Expected released, got {r2}"
        assert not (d / f"{bid}.json").exists(), "Claim file should be deleted"

        r3 = release_claim(
            "fix containers on 192.168.86.201",  # onex-allow-internal-ip
            "agent-alpha",
            d,
        )
        assert r3["action"] == "not_found", f"Expected not_found, got {r3}"

        import json as _json

        print(_json.dumps({"r1": r1, "r2": r2, "r3": r3}, indent=2))
        print("SMOKE TEST PASSED")
