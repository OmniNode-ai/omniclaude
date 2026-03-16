# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the no-untyped-metadata pre-commit hook.

OMN-5135: Hook centralized in onex_change_control; installed as
``check-no-untyped-metadata`` CLI entry point.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

_CLI = shutil.which("check-no-untyped-metadata")
_skip = pytest.mark.skipif(
    _CLI is None, reason="check-no-untyped-metadata not installed"
)


@_skip
@pytest.mark.unit
def test_detects_untyped_metadata():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("metadata: dict[str, Any] = Field(default_factory=dict)\n")
        path = f.name
    result = subprocess.run(
        ["check-no-untyped-metadata", path],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "untyped metadata dict" in result.stdout
    Path(path).unlink()


@_skip
@pytest.mark.unit
def test_passes_with_exclude_comment():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(
            "metadata: dict[str, Any] = Field(...)  # ONEX_EXCLUDE: dict_str_any - extensibility\n"
        )
        path = f.name
    result = subprocess.run(
        ["check-no-untyped-metadata", path],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    Path(path).unlink()


@_skip
@pytest.mark.unit
def test_passes_with_typed_dict():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(
            "metadata: OutputMetadataDict = Field(default_factory=lambda: OutputMetadataDict())\n"
        )
        path = f.name
    result = subprocess.run(
        ["check-no-untyped-metadata", path],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    Path(path).unlink()
