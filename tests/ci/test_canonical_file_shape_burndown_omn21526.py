# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-21526: the canonical-file-shape switch holds in this repository.

The hook and the CI job run the ``node_canonical_file_shape_check_compute`` entry of one
omnibase_core dev-merge tag, and the findings that entry added over the shrink-only
baseline sit in ``.onex_ratchets/canonical_file_shape_burndown_baseline.txt``, named for
this ticket. The canary cases run that entry, at the pin the hook and the CI job share,
against a planted repository: one new unbound handler is refused, one added burn-down
line for an existing refused file is refused, and an unchanged tree is accepted.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CORE_URL = "https://github.com/OmniNode-ai/omnibase_core"
ENTRY = (
    "omnibase_core.nodes.node_canonical_file_shape_check_compute."
    "runtime_canonical_file_shape_check"
)
TICKET = "OMN-21526"
BASELINE = ".onex_ratchets/canonical_file_shape_baseline.txt"
BURNDOWN = ".onex_ratchets/canonical_file_shape_burndown_baseline.txt"
BURNDOWN_HEADER = f"# Burn-down ticket: {TICKET}\n"
REFUSED_FILE = "bin/old_tool.sh"
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


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _core_spec() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    spec: str = workflow["jobs"]["canonical-file-shape"]["env"][
        "CANONICAL_FILE_SHAPE_CORE"
    ]
    return spec


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _ratchet(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            _core_spec(),
            "python",
            "-m",
            ENTRY,
            "--rules",
            "file-shape",
            "--base",
            base,
            "--head",
            "HEAD",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


@pytest.fixture
def planted_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repository whose one refused file is listed in a burn-down file."""
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / REFUSED_FILE).write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    (repo / BASELINE).parent.mkdir()
    (repo / BASELINE).write_text("# baseline\n", encoding="utf-8")
    (repo / BURNDOWN).write_text(f"{BURNDOWN_HEADER}{REFUSED_FILE}\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    return repo, _commit(repo, f"base {TICKET}")


def test_the_committed_burndown_file_names_this_ticket() -> None:
    lines = (ROOT / BURNDOWN).read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith(f"# Burn-down ticket: {TICKET}")
    entries = [line for line in lines if line and not line.startswith("#")]
    assert entries == sorted(set(entries))
    baseline = (ROOT / BASELINE).read_text(encoding="utf-8").splitlines()
    assert not set(entries) & set(baseline)


def test_unchanged_tree_with_listed_refused_file_is_accepted(
    planted_repo: tuple[Path, str],
) -> None:
    repo, base = planted_repo
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    _commit(repo, f"docs {TICKET}")
    result = _ratchet(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_new_unbound_handler_is_refused(planted_repo: tuple[Path, str]) -> None:
    repo, base = planted_repo
    (repo / "src/pkg/handlers").mkdir(parents=True)
    (repo / "src/pkg/handlers/handler_planted.py").write_text(
        "def handle(request):\n    return request\n", encoding="utf-8"
    )
    _commit(repo, f"plant a handler {TICKET}")
    result = _ratchet(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[handler_outside_node]" in result.stdout + result.stderr


def test_a_burndown_line_added_for_an_existing_refused_file_is_refused(
    planted_repo: tuple[Path, str],
) -> None:
    repo, base = planted_repo
    other = "bin/other_old_tool.sh"
    (repo / other).write_text("#!/bin/sh\necho other\n", encoding="utf-8")
    base = _commit(repo, f"second refused file, unlisted {TICKET}")
    with (repo / BURNDOWN).open("a", encoding="utf-8") as handle:
        handle.write(f"{other}\n")
    _commit(repo, f"list it {TICKET}")
    result = _ratchet(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[baseline-growth]" in result.stdout + result.stderr
