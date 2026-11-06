# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The transcript archiver must find the infrastructure clone wherever it lives.

OMN-17427. ``transcript-s3-archive-sync.sh`` used to hardcode the sync script at
``$OMNI_HOME/infrastructure/scripts/archive_claude_sessions.sh``. On a host whose
clone is not a sibling of the registry root, that path never resolved and the agent
exited 1 on every run while launchd reported the job as loaded and healthy. The
archive took nothing for 38 days and nobody read the exit code.

These tests run the script's own resolution, so a regression in the candidate order
fails here rather than silently on one host. They never reach AWS: resolution happens
before the first ``aws`` call, and each case stops the script at that point.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "transcript-s3-archive-sync.sh"
)
SYNC_REL = Path("scripts") / "archive_claude_sessions.sh"
INFRA_DIR = "infra_clone"  # the archiver finds the clone by its script, not its name


def _make_clone(root: Path) -> Path:
    """Create a fake infrastructure clone whose sync script is executable."""
    script = root / SYNC_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    # Echo the marker and exit non-zero, so the archiver stops here instead of
    # continuing into the AWS discovery below it.
    script.write_text("#!/usr/bin/env bash\necho RESOLVED_SYNC_RAN\nexit 9\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Strip anything that would let a real host layout leak into the case.
    for key in ("OMNINODE_INFRA_PATH", "OMNI_HOME"):
        env.pop(key, None)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"{SCRIPT} is missing"


def test_resolves_the_registry_root_sibling(tmp_path: Path) -> None:
    """The lab-host layout: a clone directly under $OMNI_HOME."""
    registry_root = tmp_path / "omni"
    _make_clone(registry_root / INFRA_DIR)
    result = _run({"OMNI_HOME": str(registry_root), "HOME": str(tmp_path / "nohome")})
    assert "infra sync script:" in result.stdout
    assert str(registry_root / INFRA_DIR / SYNC_REL) in result.stdout


def test_resolves_the_repos_root_beside_the_config_tree(tmp_path: Path) -> None:
    """Candidate 3: the operator-Mac layout, $HOME/OmniNode/repos/infrastructure.

    This is the case the old hardcoded path could not reach, and the one that left
    the archive silent for 38 days.
    """
    registry_root = tmp_path / "code" / "omni"
    registry_root.mkdir(parents=True)
    home = tmp_path / "home"
    _make_clone(home / "OmniNode" / "repos" / INFRA_DIR)
    result = _run({"OMNI_HOME": str(registry_root), "HOME": str(home)})
    assert str(home / "OmniNode" / "repos" / INFRA_DIR / SYNC_REL) in result.stdout


def test_an_explicit_override_wins_over_every_discovered_path(tmp_path: Path) -> None:
    """Candidate 1 is first, so a host with its clone somewhere else can say so."""
    registry_root = tmp_path / "omni"
    _make_clone(registry_root / INFRA_DIR)  # a resolvable sibling exists too
    override = tmp_path / "elsewhere" / INFRA_DIR
    _make_clone(override)
    result = _run(
        {
            "OMNI_HOME": str(registry_root),
            "HOME": str(tmp_path / "nohome"),
            "OMNINODE_INFRA_PATH": str(override),
        }
    )
    assert str(override / SYNC_REL) in result.stdout
    assert str(registry_root / INFRA_DIR / SYNC_REL) not in result.stdout


def test_a_trailing_slash_on_the_override_still_resolves(tmp_path: Path) -> None:
    registry_root = tmp_path / "omni"
    registry_root.mkdir(parents=True)
    override = tmp_path / "elsewhere" / INFRA_DIR
    _make_clone(override)
    result = _run(
        {
            "OMNI_HOME": str(registry_root),
            "HOME": str(tmp_path / "nohome"),
            "OMNINODE_INFRA_PATH": str(override) + "/",
        }
    )
    assert str(override / SYNC_REL) in result.stdout


def test_refusal_names_every_candidate_it_tried(tmp_path: Path) -> None:
    """The negative control. A refusal that does not say where it looked is why
    this defect survived 38 days, so the message is part of the contract."""
    registry_root = tmp_path / "omni"
    registry_root.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir(parents=True)
    result = _run({"OMNI_HOME": str(registry_root), "HOME": str(home)})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "REFUSED" in result.stderr
    assert "OMNINODE_INFRA_PATH" in result.stderr
    assert f"{registry_root}/*/{SYNC_REL}" in result.stderr
    assert f"{home}/OmniNode/repos/*/{SYNC_REL}" in result.stderr
    assert f"{registry_root.parent}/*/{SYNC_REL}" in result.stderr


def test_registry_root_unset_is_still_a_loud_refusal(tmp_path: Path) -> None:
    result = _run({"HOME": str(tmp_path)})
    assert result.returncode != 0
    assert "OMNI_HOME" in result.stderr


@pytest.mark.parametrize("marker", ["list-buckets", "aws s3"])
def test_resolution_happens_before_any_aws_call(marker: str) -> None:
    """Guard the ordering the tests above rely on: the clone is resolved first, so
    a refusal cannot be mistaken for an AWS or credential failure."""
    body = SCRIPT.read_text()
    resolve_at = body.index("INFRA_SYNC_ROOTS=")
    assert marker in body
    assert resolve_at < body.index(marker)
