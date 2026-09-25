# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the shared merge-base anti-growth baseline gate (OMN-19677)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_gate() -> Any:
    path = _REPO_ROOT / "scripts" / "anti_growth_baseline.py"
    spec = importlib.util.spec_from_file_location("anti_growth_baseline", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate: Any = _load_gate()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        env=scrub_git_location_env(os.environ),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("parser", "base_text", "head_text"),
    [
        (
            "yaml-list:violations",
            "violations:\n  - old\n",
            "violations:\n  - old\n  - new\n",
        ),
        (
            "yaml-count-map:baseline",
            "baseline:\n  old: 1\n",
            "baseline:\n  old: 1\n  new: 1\n",
        ),
        ("yaml-count-map:baseline", "baseline:\n  old: 1\n", "baseline:\n  old: 2\n"),
        (
            "json-list:findings",
            '{"findings": [{"id": "old"}]}',
            '{"findings": [{"id": "old"}, {"id": "new"}]}',
        ),
        (
            "yaml-list-tree",
            "violations:\n  - old\nopen_repairs:\n  - repair\n",
            "violations:\n  - old\nopen_repairs:\n  - repair\n  - new\n",
        ),
        ("line-set", "old\n", "old\nnew\n"),
        ("number", "4\n", "5\n"),
    ],
)
def test_growth_is_rejected(parser: str, base_text: str, head_text: str) -> None:
    failures = gate.compare_texts(base_text, head_text, parser)
    assert failures


@pytest.mark.unit
@pytest.mark.parametrize(
    ("parser", "base_text", "head_text"),
    [
        (
            "yaml-list:violations",
            "violations:\n  - old\n  - fixed\n",
            "violations:\n  - old\n",
        ),
        (
            "yaml-count-map:baseline",
            "baseline:\n  old: 2\n  fixed: 1\n",
            "baseline:\n  old: 1\n",
        ),
        (
            "json-list:findings",
            '{"findings": [{"id": "old"}, {"id": "fixed"}]}',
            '{"findings": [{"id": "old"}]}',
        ),
        (
            "yaml-list-tree",
            "violations:\n  - old\nopen_repairs:\n  - fixed\n",
            "violations:\n  - old\nopen_repairs: []\n",
        ),
        ("line-set", "old\nfixed\n", "old\n"),
        ("number", "5\n", "4\n"),
    ],
)
def test_unchanged_or_shrunk_baseline_passes(
    parser: str, base_text: str, head_text: str
) -> None:
    assert gate.compare_texts(base_text, head_text, parser) == []
    assert gate.compare_texts(base_text, base_text, parser) == []


@pytest.mark.unit
def test_merge_base_is_the_authority(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    baseline = repo / "baseline.txt"
    baseline.write_text("old\n", encoding="utf-8")
    _git(repo, "add", "baseline.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "switch", "-c", "feature")

    baseline.write_text("old\nnew\n", encoding="utf-8")
    assert gate.check_repository_baseline(repo, Path("baseline.txt"), "line-set", "dev")

    baseline.write_text("old\n", encoding="utf-8")
    assert (
        gate.check_repository_baseline(repo, Path("baseline.txt"), "line-set", "dev")
        == []
    )


@pytest.mark.unit
def test_positive_control_is_parser_specific() -> None:
    parsers = (
        "yaml-list:violations",
        "yaml-count-map:baseline",
        "json-list:findings",
        "yaml-list-tree",
        "line-set",
        "number",
    )
    for parser in parsers:
        assert gate.run_positive_control(parser) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "parser",
    ["yaml-list", "yaml-count-map:", "json-list", "unknown", "yaml-list:a..b"],
)
def test_invalid_parser_spec_fails_closed(parser: str) -> None:
    with pytest.raises(gate.BaselineParseError):
        gate.parse_parser_spec(parser)
