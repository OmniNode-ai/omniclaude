# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Runner for post_tool_use_agent_result_verifier.sh.

Reads an agent turn body on stdin, extracts claims via
`agent_claim_extractor.extract_claims`, sends them to omnimarket
`node_claim_resolver`, and exits 2 with a structured JSON diff when any
claim is fabricated or misstated.

Contract:
    stdin:  raw agent turn body (free-form text)
    env:    REPO_HINT — repository slug used to qualify PR references;
            empty/unset => bare "#N" refs, which the resolver may skip.
    stdout: JSON `{"mismatches": [...]}` when exit=2; nothing on exit=0.
    stderr: diagnostics; "RESOLVER_UNREACHABLE:..." on resolver absence/timeout.

Exit codes:
    0 — all verifiable claims passed or no claims / resolver unreachable.
    2 — at least one claim was verified to be fabricated/misstated.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess  # nosec: B404 - resolver CLI invocation is the core mechanism.
import sys
from collections.abc import Callable

from plugins.onex.hooks.lib.agent_claim_extractor import extract_claims

_RESOLVER_TIMEOUT_SECONDS = 30
Resolver = Callable[[dict[str, object]], dict[str, object]]


class ResolverUnavailable(RuntimeError):
    """Raised when node_claim_resolver cannot be reached."""


def _resolver_command() -> list[str]:
    configured = os.environ.get("OMN_CLAIM_RESOLVER_CMD")
    if configured:
        return shlex.split(configured)
    return [sys.executable, "-m", "omnimarket.nodes.node_claim_resolver"]


def _resolve_claims_via_node(payload: dict[str, object]) -> dict[str, object]:
    """Call omnimarket node_claim_resolver with the normalized claim payload."""
    proc = subprocess.run(  # nosec: B603 - fixed resolver command, no shell.
        _resolver_command(),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=_RESOLVER_TIMEOUT_SECONDS,
        check=False,
    )
    try:
        response = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ResolverUnavailable(f"invalid resolver JSON: {exc}") from exc
    if proc.returncode not in (0, 2):
        detail = proc.stderr.strip()[:300] or f"resolver exit {proc.returncode}"
        raise ResolverUnavailable(detail)
    if not isinstance(response, dict):
        raise ResolverUnavailable("resolver returned non-object JSON")
    return response


def run(
    body: str,
    repo_hint: str | None,
    *,
    resolver: Resolver | None = None,
    repo_root: str | None = None,
) -> int:
    """Extract and verify claims. See module docstring for the contract."""
    claims = extract_claims(body, repo_hint=repo_hint)
    if not claims:
        return 0

    payload: dict[str, object] = {
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "repo_hint": repo_hint,
        "repo_root": repo_root or os.environ.get("OMN_CLAIM_RESOLVER_REPO_ROOT"),
    }
    resolve = resolver or _resolve_claims_via_node
    try:
        response = resolve(payload)
    except (FileNotFoundError, subprocess.TimeoutExpired, ResolverUnavailable) as exc:
        print(f"RESOLVER_UNREACHABLE:{exc}", file=sys.stderr)
        return 0

    mismatches = _extract_mismatches(response)

    if mismatches:
        print(
            json.dumps(
                {
                    "mismatches": mismatches,
                    "claim_count": len(claims),
                },
                indent=2,
            )
        )
        return 2
    return 0


def _extract_mismatches(response: dict[str, object]) -> list[object]:
    mismatches = response.get("mismatches", [])
    if isinstance(mismatches, list):
        return mismatches
    if isinstance(mismatches, tuple):
        return list(mismatches)
    raise ResolverUnavailable("resolver response has non-list mismatches")


def main() -> int:
    body = sys.stdin.read()
    repo_hint = os.environ.get("REPO_HINT") or None
    return run(body, repo_hint)


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "run"]
