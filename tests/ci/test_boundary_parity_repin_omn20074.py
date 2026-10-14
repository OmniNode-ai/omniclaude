# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074: the boundary-parity job runs omnibase_core's manifest without the change control repo.

omnibase_core#1972 removed the only boundary whose producer lived in
onex_change_control (contract-drift-detected.v1). The validate-boundaries action
at the pin before that commit still lists the boundary, and with
onex_change_control absent from ``repos`` the parity handler exits 1 on the
missing producer file. So the action pin and the ``repos`` input move together:
this file pins both. The scan reads the parsed workflow, so a comment naming
either cannot trip it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTION = "OmniNode-ai/omnibase_core/.github/actions/validate-boundaries"
# omnibase_core#1972 merged to dev.
CORE_1972_MERGE = "c1f8e8fe0c513c0ac70ad666433a3ce1cec136c1"
PEERS = (
    "omniclaude",
    "omnidash",
    "omniintelligence",
    "omnibase_infra",
    "omnibase_core",
    "omnimemory",
    "omnimarket",
)


def _validate_boundaries_steps() -> list[tuple[str, str, dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (data.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith(f"{ACTION}@"):
                    rows.append((path.name, job_id, step))
    return rows


def test_ci_runs_the_validate_boundaries_action_once() -> None:
    rows = _validate_boundaries_steps()
    assert [(name, job) for name, job, _ in rows] == [("ci.yml", "boundary-parity")]


def test_validate_boundaries_pin_is_the_core_1972_merge() -> None:
    for name, job, step in _validate_boundaries_steps():
        pin = step["uses"].split("@", 1)[1]
        assert pin == CORE_1972_MERGE, f"{name}:{job} pins {pin}"


def test_validate_boundaries_repos_name_no_change_control_repo() -> None:
    for name, job, step in _validate_boundaries_steps():
        repos = [r.strip() for r in step["with"]["repos"].split(",")]
        assert repos == list(PEERS), f"{name}:{job} repos {repos}"
