# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""omniclaude reads omnibase-core from a dev merge tag, not a PyPI release (OMN-18595).

internal-sibling-pins refuses a moved release pin whenever the sibling carries a
dev merge tag newer than the release, and omnibase_core is dev-tagged on every
merge. Every omnibase-core release bump (omniclaude#3038, #3042, #3063, #3102) was
red for that reason. omnimarket and omnibase_infra already read core by dev tag;
these tests hold omniclaude to the same form.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.version import Version

from omniclaude.enums.enum_sibling_pin_verdict import EnumSiblingPinVerdict
from omniclaude.handlers.handler_dev_merge_tag import dev_merge_tag_stamp
from omniclaude.handlers.handler_internal_sibling_pins import handle
from omniclaude.models.model_internal_sibling_pins import (
    ModelInternalSiblingPinsRequest,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_GIT = "https://github.com/OmniNode-ai/omnibase_core.git"
# The release whose cascade PRs could not land; the pin must carry at least it.
FLOOR = Version("0.47.61")
# A dev merge tag later than any release, as core's dev always has one.
LATER_DEV_TAG = "dev-29991231235959-000000000000"


def _lock_text() -> str:
    return (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")


def _locked_core() -> dict[str, object]:
    packages = tomllib.loads(_lock_text())["package"]
    cores = [p for p in packages if p["name"] == "omnibase-core"]
    assert len(cores) == 1, f"uv.lock resolves omnibase-core {cores}"
    return cores[0]


def _source_tag() -> str | None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    source = pyproject["tool"]["uv"]["sources"].get("omnibase-core")
    if not isinstance(source, dict):
        return None
    assert source.get("git") == CORE_GIT, source
    assert set(source) == {"git", "tag"}, source
    return str(source["tag"])


def test_pyproject_reads_core_from_a_dev_merge_tag() -> None:
    tag = _source_tag()
    assert tag is not None, "pyproject.toml has no [tool.uv.sources] omnibase-core"
    assert dev_merge_tag_stamp(tag) is not None, tag


def test_lock_resolves_core_at_that_dev_merge_tag() -> None:
    core = _locked_core()
    source = core["source"]
    assert isinstance(source, dict), source
    git = str(source.get("git", ""))
    assert git.startswith(f"{CORE_GIT}?tag={_source_tag()}#"), git
    assert Version(str(core["version"])) >= FLOOR, core["version"]


def test_internal_sibling_pins_allows_the_core_pin_behind_a_newer_dev_tag() -> None:
    result = handle(
        ModelInternalSiblingPinsRequest(
            head_lock_text=_lock_text(),
            base_lock_text=None,
            dev_tags={"omnibase_core": [LATER_DEV_TAG]},
        )
    )
    verdicts = {f.distribution: f.verdict for f in result.findings}
    assert verdicts["omnibase-core"] is EnumSiblingPinVerdict.ALLOWED, verdicts


def test_core_check_local_paths_hook_pins_at_least_the_floor() -> None:
    """The release-tagged core hook block runs 0.47.61 or later, where check-local-paths runs core's compute node."""
    lines = (
        (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8").splitlines()
    )
    hook_at = next(i for i, line in enumerate(lines) if "id: check-local-paths" in line)
    rev_line = next(
        line for line in reversed(lines[:hook_at]) if line.strip().startswith("rev:")
    )
    rev = rev_line.split(":", 1)[1].strip()
    assert rev.startswith("v"), rev
    assert Version(rev[1:]) >= FLOOR, rev
