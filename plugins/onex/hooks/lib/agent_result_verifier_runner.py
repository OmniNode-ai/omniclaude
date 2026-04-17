# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Runner for post_tool_use_agent_result_verifier.sh (OMN-9055 Task 4 scaffold).

Reads an agent turn body on stdin, extracts claims via
`agent_claim_extractor.extract_claims`, probes each `pr_merged` claim via
`gh pr view`, and exits 2 with a structured JSON diff when any claim is
fabricated (PR missing) or misstated (PR exists but not merged).

Scaffold scope — only `pr_merged` is probed; `thread_resolved` and
`linear_state` short-circuit to PASS. The maturity ticket replaces the
inline `gh` probe with a real omnimarket claim-resolver node.

Contract:
    stdin:  raw agent turn body (free-form text)
    env:    REPO_HINT — repository slug used to qualify PR references;
            empty/unset => bare "#N" refs, which are skipped by the probe.
    stdout: JSON `{"mismatches": [...]}` when exit=2; nothing on exit=0.
    stderr: diagnostics; "RESOLVER_UNREACHABLE:..." on gh absence/timeout.

Exit codes:
    0 — all verifiable claims passed or no claims / resolver unreachable.
    2 — at least one claim was verified to be fabricated/misstated.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec: B404 - gh CLI invocation is the core mechanism
import sys

from plugins.onex.hooks.lib.agent_claim_extractor import extract_claims

_GH_TIMEOUT_SECONDS = 10


def _probe_pr_merged(repo: str, number: str) -> tuple[str, str] | None:
    """Probe whether a PR exists and is merged via `gh pr view`.

    Returns:
        None when the PR is confirmed merged (no mismatch).
        ("reason", "detail") on mismatch.

    Raises:
        Caller handles FileNotFoundError and TimeoutExpired as fail-open.
    """
    proc = subprocess.run(  # nosec: B603,B607 - gh CLI is the verifier bridge
        [
            "gh",
            "pr",
            "view",
            number,
            "--repo",
            f"OmniNode-ai/{repo}",
            "--json",
            "state,number",
        ],
        capture_output=True,
        text=True,
        timeout=_GH_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        return (
            f"PR {repo}#{number} not found on GitHub",
            proc.stderr.strip()[:200],
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    state = data.get("state", "").upper()
    if state != "MERGED":
        return (f"PR {repo}#{number} state is {state!r}, not MERGED", "")
    return None


def run(body: str, repo_hint: str | None) -> int:
    """Extract and verify claims. See module docstring for the contract."""
    claims = extract_claims(body, repo_hint=repo_hint)
    mismatches: list[dict[str, object]] = []

    for claim in claims:
        if claim.kind != "pr_merged":
            # Scaffold short-circuit — maturity ticket routes the full
            # taxonomy through a real resolver node.
            continue
        repo, _, number = claim.ref.partition("#")
        if not repo or not number:
            # Bare `#N` (no repo_hint); can't probe without context.
            continue
        try:
            result = _probe_pr_merged(repo, number)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"RESOLVER_UNREACHABLE:{exc}", file=sys.stderr)
            return 0
        if result is not None:
            reason, detail = result
            entry: dict[str, object] = {
                "claim": claim.model_dump(),
                "reason": reason,
            }
            if detail:
                entry["gh_stderr"] = detail
            mismatches.append(entry)

    if mismatches:
        print(json.dumps({"mismatches": mismatches}, indent=2))
        return 2
    return 0


def main() -> int:
    body = sys.stdin.read()
    repo_hint = os.environ.get("REPO_HINT") or None
    return run(body, repo_hint)


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "run"]
