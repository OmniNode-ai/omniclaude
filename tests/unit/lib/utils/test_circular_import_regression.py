# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression test: importing through omniclaude.lib must not trigger circular import."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
class TestCircularImportRegression:
    """Verify the circular import chain is broken."""

    def test_import_task_classifier_via_lib(self) -> None:
        """Importing TaskClassifier must not raise AttributeError from circular import."""
        result = subprocess.run(
            [sys.executable, "-c", "from omniclaude.lib.task_classifier import TaskClassifier; print(TaskClassifier)"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "TaskClassifier" in result.stdout

    def test_import_quality_enforcer_via_lib(self) -> None:
        """Importing QualityEnforcer must not raise AttributeError."""
        result = subprocess.run(
            [sys.executable, "-c", "from omniclaude.lib.utils.quality_enforcer import QualityEnforcer; print(QualityEnforcer)"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "QualityEnforcer" in result.stdout

    def test_import_debug_utils_via_lib(self) -> None:
        """Importing debug_utils must not raise AttributeError."""
        result = subprocess.run(
            [sys.executable, "-c", "from omniclaude.lib.utils.debug_utils import INTELLIGENCE_SERVICE_URL; print('OK')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "OK" in result.stdout, f"Expected 'OK' in stdout, got: {result.stdout!r}"

    def test_lib_lazy_attribute_access(self) -> None:
        """Lazy __getattr__ resolves subpackages on attribute access."""
        result = subprocess.run(
            [sys.executable, "-c", (
                "import omniclaude.lib as lib; "
                "assert lib.utils is not None; "
                "assert lib.models is not None; "
                "assert lib.core is not None; "
                "print('OK')"
            )],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Lazy attribute access failed: {result.stderr}"
        assert "OK" in result.stdout
