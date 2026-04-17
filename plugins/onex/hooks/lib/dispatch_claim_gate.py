# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dispatch claim gate — extractor rules + acquire/block logic (OMN-8928).

Deterministic rule-based extraction of blocker_id from Claude tool input.
No LLM involvement — regex rules guarantee consistency.

Extraction precedence (first match wins):
  1. Explicit frontmatter:  blocker_id: <40-char-hex>
  2. SSH 201 host:           ssh ... 192.168.86.201  # onex-allow-internal-ip
  3. rpk topic produce:      rpk topic produce ... rebuild
  4. fix-containers keyword: "fix containers on 192.168.86.201"  # onex-allow-internal-ip
  5. OMN ticket:             OMN-XXXX in Agent prompt
  6. PR merge ref:           gh pr merge --repo OmniNode-ai/repo N
  7. No match -> None (pass through)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Pattern constants
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

_DEFAULT_TTL = 300


def extract_blocker_info(tool_input: str) -> tuple[str, str, str] | None:
    """Extract (kind, host, resource) from tool input text.

    Returns None if no rule matches (caller should pass through).
    """
    if _RE_EXPLICIT.search(tool_input):
        m = _RE_EXPLICIT.search(tool_input)
        assert m is not None
        return ("explicit", "local", m.group(1))

    if _RE_SSH_201.search(tool_input):
        return ("ssh_201", "192.168.86.201", "ssh_session")  # onex-allow-internal-ip

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
        ticket = f"OMN-{m.group(1)}"
        return ("ticket_dispatch", "local", ticket)

    m = _RE_PR_MERGE.search(tool_input)
    if m:
        repo = m.group(1)
        pr_num = m.group(2)
        return ("pr_merge", "github.com", f"OmniNode-ai/{repo}#{pr_num}")

    return None


def check_and_acquire(
    tool_input: str,
    claimant: str,
    claims_dir: Path,
    ttl_seconds: int = _DEFAULT_TTL,
) -> dict[str, object]:
    """Check if a claim exists for this tool_input; acquire if not.

    Returns a result dict:
      {"action": "pass"}                       — no rule matched
      {"action": "acquired", "blocker_id": X}  — claim newly acquired
      {"action": "blocked", "blocker_id": X, "held_by": Y, "ttl_remaining": Z}
    """
    info = extract_blocker_info(tool_input)
    if info is None:
        return {"action": "pass"}

    kind, host, resource = info

    # Handle explicit blocker_id (resource IS the sha1)
    if kind == "explicit":
        blocker_id = resource
    else:
        blocker_id = hashlib.sha1(
            f"{kind}|{host}|{resource}".encode(), usedforsecurity=False
        ).hexdigest()

    existing = is_claimed_from_dir(blocker_id, claims_dir)
    if existing is not None:
        held_by = str(existing.get("claimant", "unknown"))
        ttl_rem = _ttl_remaining(existing)
        if held_by == claimant:
            return {"action": "pass"}
        return {
            "action": "blocked",
            "blocker_id": blocker_id,
            "held_by": held_by,
            "ttl_remaining": ttl_rem,
            "kind": kind,
            "host": host,
            "resource": resource,
        }

    claim_data: dict[str, object] = {
        "blocker_id": blocker_id,
        "kind": kind,
        "host": host,
        "resource": resource,
        "claimant": claimant,
        "claimed_at": datetime.now(tz=UTC).isoformat(),
        "ttl_seconds": ttl_seconds,
        "tool_name": "Agent",
    }

    if acquire_claim_from_dir(claim_data, claims_dir):
        return {"action": "acquired", "blocker_id": blocker_id}

    # Race: another agent acquired between our check and O_CREAT
    existing2 = is_claimed_from_dir(blocker_id, claims_dir)
    held_by2 = str(existing2.get("claimant", "unknown")) if existing2 else "unknown"
    ttl_rem2 = _ttl_remaining(existing2) if existing2 else 0.0
    return {
        "action": "blocked",
        "blocker_id": blocker_id,
        "held_by": held_by2,
        "ttl_remaining": ttl_rem2,
        "kind": kind,
        "host": host,
        "resource": resource,
    }


def _ttl_remaining(claim_data: dict[str, object]) -> float:
    try:
        claimed_at = datetime.fromisoformat(str(claim_data["claimed_at"]))
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=UTC)
        ttl = int(str(claim_data.get("ttl_seconds", 300)))
        elapsed = (datetime.now(tz=UTC) - claimed_at).total_seconds()
        return max(0.0, float(ttl) - elapsed)
    except (KeyError, ValueError):
        return 0.0


def is_claimed_from_dir(blocker_id: str, claims_dir: Path) -> dict[str, object] | None:
    """Check claim directly from a given directory (for testability)."""
    import json as _json

    p = claims_dir / f"{blocker_id}.json"
    if not p.exists():
        return None
    try:
        data: dict[str, object] = _json.loads(p.read_text())
        # Check expiry
        claimed_at_str = str(data.get("claimed_at", ""))
        if claimed_at_str:
            claimed_at = datetime.fromisoformat(claimed_at_str)
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=UTC)
            ttl = int(str(data.get("ttl_seconds", 300)))
            if (datetime.now(tz=UTC) - claimed_at).total_seconds() >= ttl:
                p.unlink(missing_ok=True)
                return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def acquire_claim_from_dir(claim_data: dict[str, object], claims_dir: Path) -> bool:
    """Atomically write claim to given directory (for testability)."""
    import os as _os

    blocker_id = str(claim_data["blocker_id"])
    p = claims_dir / f"{blocker_id}.json"
    payload = json.dumps(claim_data, default=str).encode()
    try:
        fd = _os.open(str(p), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    try:
        _os.write(fd, payload)
    finally:
        _os.close(fd)
    return True


if __name__ == "__main__":
    # CLI smoke test: python3 dispatch_claim_gate.py check <claims_dir>
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        d = Path(sys.argv[2])
        d.mkdir(parents=True, exist_ok=True)
        result1 = check_and_acquire(
            "fix containers on 192.168.86.201",  # onex-allow-internal-ip
            "agent-smoke-1",
            d,
        )
        result2 = check_and_acquire(
            "fix containers on 192.168.86.201",  # onex-allow-internal-ip
            "agent-smoke-2",
            d,
        )
        print(json.dumps({"first": result1, "second": result2}, indent=2))
        assert result1["action"] == "acquired", f"Expected acquired, got {result1}"
        assert result2["action"] == "blocked", f"Expected blocked, got {result2}"
        assert "held_by" in result2
        print("SMOKE TEST PASSED")
