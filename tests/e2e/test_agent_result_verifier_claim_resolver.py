# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""E2E coverage for resolver-backed agent claim verification."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_fabricated_multi_claim_turn_exits_2_with_structured_diff(
    tmp_path: Path,
) -> None:
    resolver = tmp_path / "fake_claim_resolver.py"
    resolver.write_text(
        """
from __future__ import annotations
import json
import sys

payload = json.loads(sys.stdin.read())
claims = payload["claims"]
by_kind = {claim["kind"]: claim for claim in claims}
mismatches = [
    {
        "claim": by_kind["pr_merged"],
        "status": "failed",
        "reason": "PR omniclaude#123 state mismatch",
        "expected": "MERGED",
        "actual": "OPEN",
    },
    {
        "claim": by_kind["blocker_on_X"],
        "status": "failed",
        "reason": "blocker claim lacks quoted gh pr view --json evidence",
        "expected": "quoted gh pr view --json evidence",
        "actual": "absent",
    },
]
print(json.dumps({"results": [], "mismatches": mismatches}))
sys.exit(2)
""".strip()
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["REPO_HINT"] = "omniclaude"
    env["OMN_CLAIM_RESOLVER_CMD"] = f"{sys.executable} {resolver}"

    body = (
        "PR #123 merged. Opened PR #124. CI passing for PR #124. "
        "Committed file plugins/onex/hooks/lib/agent_claim_extractor.py. "
        "Blocker on OMN-9107 without quoted evidence."
    )
    proc = subprocess.run(  # nosec: B603
        [sys.executable, "-m", "plugins.onex.hooks.lib.agent_result_verifier_runner"],
        input=body,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=30,
        check=False,
    )

    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["claim_count"] == 5
    assert len(payload["mismatches"]) == 2
    assert payload["mismatches"][0]["actual"] == "OPEN"
    assert "gh pr view --json" in payload["mismatches"][1]["reason"]
