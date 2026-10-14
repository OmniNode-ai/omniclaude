# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074: script defaults and aliases stop targeting change control.

The import scan alone cannot control this PR after the workflow retirement
already removed the package imports on dev. These assertions cover the script
references this PR still removes, without running repository mutations.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative_path",
    [
        "plugins/onex/hooks/scripts/statusline.sh",
        "scripts/apply_branch_protection.sh",
        "scripts/verify_branch_protection.sh",
        "scripts/cron-quick-merge.sh",
        "scripts/nightly-merge-sweep.sh",
        "scripts/setup-session-crons.sh",
        "scripts/user-bin/gh",
    ],
)
def test_script_defaults_do_not_target_change_control(relative_path: str) -> None:
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    active_lines = [
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    ]
    offenders = [line for line in active_lines if "onex_change_control" in line]
    assert not offenders, f"{relative_path}: {offenders}"


def test_alias_registry_rejects_retired_repository_names() -> None:
    path = REPO_ROOT / "plugins/onex/skills/_bin/_lib/repo_aliases.py"
    spec = importlib.util.spec_from_file_location("retirement_repo_aliases", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for alias in ("onex_change_control", "change_control", "ONEX_CHANGE_CONTROL"):
        with pytest.raises(module.AliasResolutionError, match="Unknown repo alias"):
            module.resolve(alias)
    assert "OmniNode-ai/onex_change_control" not in module.all_aliases().values()
    assert module.resolve("core") == "OmniNode-ai/omnibase_core"
