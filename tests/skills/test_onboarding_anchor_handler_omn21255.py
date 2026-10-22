# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The anchor selection lives in the node's Bash handler, not in the script.

``handler_onboarding_preflight.sh`` owns proven_pin, anchor_time,
anchored_commit, checkout_anchored and clone_at_anchor; lab-onboarding.sh only
names INFRA_ANCHOR and calls them.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO = Path(__file__).resolve().parents[2]
NODE = REPO / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
HANDLER = NODE / "handler_onboarding_preflight.sh"
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
FUNCTIONS = (
    "proven_pin",
    "anchor_time",
    "anchored_commit",
    "checkout_anchored",
    "clone_at_anchor",
)
PIN = "b" * 40

pytestmark = pytest.mark.unit


def _git(repo: Path, *args: str, when: str | None = None) -> str:
    env = {
        **scrub_git_location_env(os.environ),
        "HOME": str(repo),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "F",
        "GIT_AUTHOR_EMAIL": "f@example.invalid",
        "GIT_COMMITTER_NAME": "F",
        "GIT_COMMITTER_EMAIL": "f@example.invalid",
    }
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, when: str) -> str:
    (repo / "f").write_text(name)
    _git(repo, "add", "f")
    _git(repo, "commit", "-q", "-m", name, when=when)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def ws(tmp_path: Path) -> dict[str, str]:
    """A workspace with omnibase_infra (anchor a1, then a2) and one unpinned repo."""
    workspace = tmp_path / "ws"
    infra, other = workspace / "omnibase_infra", workspace / "other"
    for repo in (infra, other):
        repo.mkdir(parents=True)
        _git(repo, "init", "-q", "-b", "dev")
    (infra / ".github").mkdir()
    a1 = _commit(infra, "a1", "2001-09-09T01:46:40+00:00")
    a2 = _commit(infra, "a2", "2001-09-09T03:00:00+00:00")
    o1 = _commit(other, "o1", "2001-09-09T01:00:00+00:00")
    o2 = _commit(other, "o2", "2001-09-09T02:00:00+00:00")
    for repo in (infra, other):
        _git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
        _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev")
    (infra / ".github/sibling-pins.yaml").write_text(
        f"pins:\n  pinned: {PIN}\nother_key:\n  other: {'c' * 40}\n"
    )
    return {
        "workspace": str(workspace),
        "a1": a1,
        "a2": a2,
        "o1": o1,
        "o2": o2,
    }


def _run(ws: dict[str, str], body: str) -> subprocess.CompletedProcess[str]:
    section = subprocess.run(
        ["awk", "/^# The anchor: which commit/ { on = 1 } on { print }", str(HANDLER)],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f"""
            say() {{ printf '%s\\n' "$*"; }}
            clone_default_branch() {{ printf dev; }}
            WORKSPACE="$1"; INFRA_ANCHOR="$2"
            {section}
            {body}
            """,
            "h",
            ws["workspace"],
            ws["a1"],
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": os.devnull},
    )


def test_handler_defines_the_anchor_functions_and_declares_them() -> None:
    text = HANDLER.read_text()
    declared = yaml.safe_load((NODE / "contract.yaml").read_text())["metadata"][
        "bootstrap_handler"
    ]["entrypoints"]
    for name in FUNCTIONS:
        assert re.search(rf"^{name}\(\) \{{", text, re.M), name
        assert name in declared, name
        assert not re.search(rf"^{name}\(\) \{{", SCRIPT.read_text(), re.M), name


def test_proven_pin_reads_only_the_pins_section(ws: dict[str, str]) -> None:
    result = _run(ws, "proven_pin pinned; echo '|'; proven_pin other; echo '|'")
    assert result.stdout == f"{PIN}\n|\n|\n"


def test_anchored_commit_infra_is_the_anchor_and_unpinned_is_time_bound(
    ws: dict[str, str],
) -> None:
    result = _run(ws, "anchored_commit omnibase_infra; anchored_commit pinned; anchored_commit other")
    # anchor time 01:46:40 sits between o1 (01:00) and o2 (02:00)
    assert result.stdout.split() == [ws["a1"], PIN, ws["o1"]]


def test_anchor_time_is_the_anchor_commit_date(ws: dict[str, str]) -> None:
    assert _run(ws, "anchor_time").stdout.strip() == "2001-09-09T01:46:40+00:00"


def test_checkout_anchored_detaches_and_clone_at_anchor_agrees(
    ws: dict[str, str],
) -> None:
    infra = Path(ws["workspace"]) / "omnibase_infra"
    result = _run(
        ws,
        'checkout_anchored omnibase_infra "$INFRA_ANCHOR" && clone_at_anchor omnibase_infra && echo ok',
    )
    assert result.stdout.strip() == "ok", result.stderr
    assert _git(infra, "rev-parse", "HEAD") == ws["a1"]
    assert _git(infra, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


def test_clone_at_anchor_is_false_off_the_anchor(ws: dict[str, str]) -> None:
    assert _run(ws, "clone_at_anchor omnibase_infra").returncode == 1


def test_checkout_anchored_refuses_a_dirty_clone(ws: dict[str, str]) -> None:
    infra = Path(ws["workspace"]) / "omnibase_infra"
    (infra / "f").write_text("dirty")
    result = _run(ws, 'checkout_anchored omnibase_infra "$INFRA_ANCHOR"')
    assert result.returncode == 1
    assert "uncommitted changes" in result.stdout
    assert _git(infra, "rev-parse", "HEAD") == ws["a2"]
