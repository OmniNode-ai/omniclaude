# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20074: the no-untyped-metadata hook runs omnibase_core's node, not OCC's script.

``check-no-untyped-metadata`` is a console script of the onex_change_control
package. omnibase_core replaced it with the COMPUTE node
``node_no_untyped_metadata_check_compute`` (in every release from v0.47.35), so
the hook must run that module through the locked omnibase-core instead.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CORE_MODULE = (
    "omnibase_core.nodes.node_no_untyped_metadata_check_compute."
    "runtime_no_untyped_metadata_check"
)
OCC_SCRIPT = "check-no-untyped-metadata"
FIRST_CORE_WITH_NODE = (0, 47, 35)


def _hooks(hook_id: str) -> list[dict[str, Any]]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [
        hook
        for block in config["repos"]
        for hook in block.get("hooks", [])
        if hook.get("id") == hook_id
    ]


def test_hook_runs_the_core_node() -> None:
    hooks = _hooks("no-untyped-metadata")
    assert len(hooks) == 1
    entry = hooks[0]["entry"]
    assert f"python -m {CORE_MODULE}" in entry
    assert OCC_SCRIPT not in entry.split()


def test_locked_core_carries_the_node() -> None:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "omnibase-core"]
    assert len(versions) == 1
    assert tuple(int(x) for x in versions[0].split(".")[:3]) >= FIRST_CORE_WITH_NODE


@pytest.mark.parametrize("hook_id", ["no-untyped-metadata"])
def test_no_hook_runs_the_occ_console_script(hook_id: str) -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    entries = [
        hook.get("entry", "")
        for block in config["repos"]
        for hook in block.get("hooks", [])
    ]
    assert entries  # positive control: the config was parsed
    assert not [e for e in entries if OCC_SCRIPT in e.split()], hook_id
