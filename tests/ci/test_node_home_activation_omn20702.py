# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The node-home ratchet is activated in this repository (OMN-20702).

A new ONEX node directory or ``onex.nodes`` entry point outside omnimarket is
refused against the shrink-only ``.onex_ratchets/node_home_baseline.txt``. The
check is the ``node-home`` rule group of the omnibase_core node
``node_canonical_file_shape_check_compute``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MODULE = (
    "omnibase_core.nodes.node_canonical_file_shape_check_compute."
    "runtime_canonical_file_shape_check"
)
NODE_HOME_BASELINE = ".onex_ratchets/node_home_baseline.txt"
# The node ships in an omnibase_core dev-merge tag, not in the PyPI release the
# project resolves, so the check runs at the pin the CI job and the hook share.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def _core_spec() -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    spec: str = workflow["jobs"]["canonical-file-shape"]["env"][
        "CANONICAL_FILE_SHAPE_CORE"
    ]
    return spec


def _baseline_entries() -> list[str]:
    baseline = ROOT / NODE_HOME_BASELINE
    assert baseline.is_file(), f"{NODE_HOME_BASELINE} is missing"
    return [
        line
        for line in baseline.read_text().splitlines()
        if line and not line.startswith("#")
    ]


def test_baseline_lists_only_existing_sorted_node_directories() -> None:
    entries = _baseline_entries()
    assert entries
    assert entries == sorted(set(entries))
    missing = [entry for entry in entries if not (ROOT / entry).is_dir()]
    assert missing == []


def test_check_accepts_the_tree_against_head() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            _core_spec(),
            "python",
            "-m",
            RUNTIME_MODULE,
            "--rules",
            "node-home",
            "--repo-root",
            str(ROOT),
            "--base",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_commit_runs_the_check_from_omnibase_core() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [
        (repo["repo"], hook["id"])
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
    ]
    assert (
        "https://github.com/OmniNode-ai/omnibase_core",
        "check-node-home",
    ) in hooks


def test_ci_runs_the_check_against_the_merge_base_with_a_positive_control() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert (
        "python -m omnibase_core.nodes.node_canonical_file_shape_check_compute"
        in workflow
    )
    assert "--rules node-home" in workflow
    assert 'node_home --base "$base"' in workflow
    assert "POSITIVE CONTROL FAILED: planted" in workflow
