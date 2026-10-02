# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Require retry guards for every CI dependency sync (OMN-17427)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMUM_SYNC_STEPS = 10


@pytest.mark.unit
def test_ci_uv_sync_commands_have_retry_guards() -> None:
    workflow: dict[str, Any] = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    sync_steps = 0
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            run: str = step.get("run", "")
            if "uv sync" not in run:
                continue
            sync_steps += 1
            for line in run.splitlines():
                command = line.strip()
                # Retry diagnostics mention uv sync without invoking it.
                if command.startswith(("#", "echo ")) or "uv sync" not in command:
                    continue
                assert command.startswith(("until ", "if ")), (
                    f"Unretried uv sync in {job_name}/{step.get('name', '<unnamed>')}: "
                    f"{command}"
                )
    assert sync_steps >= MINIMUM_SYNC_STEPS, (
        f"Expected at least {MINIMUM_SYNC_STEPS} uv sync steps, found {sync_steps}"
    )
