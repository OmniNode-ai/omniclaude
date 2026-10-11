# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20074 - the skip-token reusable has no escape hatch.

The approvals registry (a file in change control) and the receipt-id comment that
cited it are retired. The reusable must read no registry and must treat a skip token
as a violation on every surface, whatever comment accompanies it. The scan step's
shell is executed here against a stubbed ``gh`` so the verdict is observed, not
inferred from the text.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "reject-deploy-gate-skip.yml"
)


def _scan_run() -> str:
    doc: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    steps = doc["jobs"]["scan-skip-tokens"]["steps"]
    (scan,) = [s for s in steps if "Scan all PR surfaces" in str(s.get("name", ""))]
    return str(scan["run"])


def test_the_workflow_reads_no_registry() -> None:
    text = WORKFLOW.read_text().lower()
    for needle in (
        "skip_token_approvals",
        "validate_skip_receipt",
        "allowlist_pattern",
        "receipt_present",
        "onex_change_control",
    ):
        assert needle not in text, needle


def _run_scan(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    body_file = tmp_path / "body.txt"
    body_file.write_text(body, encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"],
        "RESOLVED_BODY_PATH": str(body_file),
        "RESOLVED_PR_NUMBER": "",
        "RUNNER_TEMP": str(tmp_path),
        "PR_TITLE": "",
    }
    return subprocess.run(
        ["bash", "-c", _scan_run()],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )


@pytest.mark.parametrize(
    "body",
    [
        "[skip-receipt-gate: x]",
        "[skip-deploy-gate: x]\n# skip-token-allowed: R-1",
        "[Skip-Anything: x]\n#  SKIP-TOKEN-ALLOWED: R-2",
    ],
)
def test_a_skip_token_fails_the_scan_with_or_without_a_receipt_comment(
    tmp_path: Path, body: str
) -> None:
    result = _run_scan(tmp_path, body)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "contains a [skip-*] bypass token" in result.stdout


def test_a_clean_body_passes_and_a_receipt_comment_alone_is_inert(
    tmp_path: Path,
) -> None:
    assert _run_scan(tmp_path, "a clean body").returncode == 0
    assert _run_scan(tmp_path, "# skip-token-allowed: R-3").returncode == 0
