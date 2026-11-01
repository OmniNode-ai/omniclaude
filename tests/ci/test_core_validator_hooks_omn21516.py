# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21516: shared validators come from core, with no repo-local copies."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

ROOT = Path(__file__).resolve().parents[2]
CORE_REPO = "https://github.com/OmniNode-ai/omnibase_core"
HOOK_IDS = ("check-ai-slop", "skip-count-ratchet")

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("hook_id", HOOK_IDS)
def test_validator_hook_has_one_core_registration(hook_id: str) -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text("utf-8"))
    matches = [
        (repo, hook)
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] == hook_id
    ]
    assert len(matches) == 1
    repo, hook = matches[0]
    assert repo["repo"] == CORE_REPO
    assert repo["rev"].startswith("dev-")
    assert repo["rev"] == "dev-20261101103701-2fc5e461fca7"
    assert "entry" not in hook


def test_local_validator_copies_are_absent() -> None:
    for directory, hook_id in zip(("validation", "ci"), HOOK_IDS, strict=True):
        filename = hook_id.replace("-", "_") + ".py"
        assert not (ROOT / "scripts" / directory / filename).exists()


def test_tracked_files_do_not_reference_local_validator_copies() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    retired_names = [hook_id.replace("-", "_") + ".py" for hook_id in HOOK_IDS]
    findings = []
    for relative in tracked.stdout.split("\0"):
        if not relative:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        contents = path.read_bytes()
        for name in retired_names:
            if name.encode("utf-8") in contents:
                findings.append(f"{relative}: {name}")
    assert not findings, "\n".join(findings)
