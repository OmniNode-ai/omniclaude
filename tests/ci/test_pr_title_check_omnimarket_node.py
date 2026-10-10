# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20885: ``pr-title / check-title`` is decided by an omnimarket node, not by change control.

The required context used to come from the check-title bash step of the
change-control repository's pr-title-check-reusable.yml. The decision now lives
in omnimarket's ``node_pr_title_check_compute`` and the caller job runs it from a
pinned omnimarket release. The context name must not move, or branch protection
would need a change: the job keeps its id ``pr-title`` and is named
``pr-title / check-title``, the name the reusable call produced.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/pr-title-check.yml"
MANIFEST = ROOT / ".github/required-checks.yaml"
CONTEXT = "pr-title / check-title"
NODE_MODULE = "omnimarket.nodes.node_pr_title_check_compute"


def _workflow() -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return loaded


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _workflow()["jobs"]["pr-title"]
    return job


def _script() -> str:
    return "\n".join(str(step.get("run", "")) for step in _job()["steps"])


def test_workflow_no_longer_calls_change_control() -> None:
    assert "onex_change_control" not in WORKFLOW.read_text()
    assert "uses" not in _job()


def test_job_keeps_the_required_context_name() -> None:
    job = _job()
    assert job["name"] == CONTEXT
    assert job["if"] == "always()"
    triggers = _workflow()[True]["pull_request"]["types"]
    assert triggers == ["opened", "edited", "synchronize", "reopened"]


def test_job_runs_the_node_from_a_pinned_omnimarket_release() -> None:
    script = _script()
    assert f"-m {NODE_MODULE}" in script
    env = {k: v for step in _job()["steps"] for k, v in (step.get("env") or {}).items()}
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(env["OMNIMARKET_VERSION"]))
    assert '"omnimarket==${OMNIMARKET_VERSION}"' in script
    assert env["PR_TITLE"] == "${{ github.event.pull_request.title }}"
    assert env["PR_AUTHOR"] == "${{ github.event.pull_request.user.login }}"


def test_manifest_row_names_the_local_producer() -> None:
    gates = yaml.safe_load(MANIFEST.read_text())["gates"]
    row = next(g for g in gates if g["name"] == CONTEXT)
    assert row["mode"] == "REQUIRED"
    assert row["producer_kind"] == "local"
    assert row["workflow"] == "pr-title-check.yml"
    assert row["job_path"] == ["pr-title"]
    assert "cross_repo_ref" not in row
    assert "onex_change_control" not in row["rationale"]
