# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI dependency-shape guards."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_intelligence_stack_is_not_a_base_dependency() -> None:
    """Default CI installs must not pull local ML/CUDA transitive packages."""

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]
    optional = pyproject["project"]["optional-dependencies"]

    assert "omninode-intelligence>=0.24.0,<0.25.0" not in dependencies
    assert "omninode-intelligence>=0.24.0,<0.25.0" in optional["intelligence"]
    assert "omninode-intelligence>=0.24.0,<0.25.0" in optional["full"]


@pytest.mark.unit
def test_lock_keeps_intelligence_behind_extras() -> None:
    """The lockfile must not expose omninode-intelligence in default metadata."""

    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    project = next(
        package for package in lock["package"] if package["name"] == "omninode-claude"
    )

    default_deps = {dep["name"] for dep in project["dependencies"]}
    assert "omninode-intelligence" not in default_deps

    requires_dist = project["metadata"]["requires-dist"]
    intelligence_deps = [
        dep for dep in requires_dist if dep["name"] == "omninode-intelligence"
    ]
    assert {dep["marker"] for dep in intelligence_deps} == {
        "extra == 'full'",
        "extra == 'intelligence'",
    }


@pytest.mark.unit
def test_dev_group_and_lock_carry_pre_commit() -> None:
    """``uv run pre-commit install`` (the contributing guide) needs pre-commit in the dev group.

    OMN-17427: on a fresh Linux clone the command failed because nothing installed pre-commit,
    so a developer had to install it as a uv tool outside the locked environment.
    """

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    dev = pyproject["dependency-groups"]["dev"]
    assert any(dep.split(">", 1)[0].split("=", 1)[0] == "pre-commit" for dep in dev)

    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    project = next(
        package for package in lock["package"] if package["name"] == "omninode-claude"
    )
    dev_locked = {dep["name"] for dep in project["dev-dependencies"]["dev"]}
    assert "pre-commit" in dev_locked
