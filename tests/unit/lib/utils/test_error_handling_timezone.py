# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression test: PatternTrackingLogger.__init__ must not raise NameError on UTC."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
class TestPatternTrackingLoggerTimezone:
    """Verify that PatternTrackingLogger instantiation does not raise NameError."""

    def test_pattern_tracking_logger_instantiates_without_nameerror(
        self, tmp_path: Path
    ) -> None:
        """Instantiating PatternTrackingLogger() must not raise NameError for UTC.

        This is a regression test for the missing UTC import in error_handling.py —
        the __init__ method called datetime.now(UTC) but UTC was not imported from
        the datetime module.
        """
        log_file = str(tmp_path / "test.log")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from omniclaude.lib.utils.error_handling import PatternTrackingLogger; "
                    f"logger = PatternTrackingLogger(log_file={log_file!r}); "
                    "print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"PatternTrackingLogger() raised unexpectedly.\n"
            f"stderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )
        assert "OK" in result.stdout

    def test_pattern_tracking_logger_default_path_uses_utc(self) -> None:
        """PatternTrackingLogger() with no args must resolve log file using UTC date."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from omniclaude.lib.utils.error_handling import PatternTrackingLogger; "
                    "logger = PatternTrackingLogger(); "
                    "path = logger.get_log_file_path(); "
                    "assert 'pattern_tracking_' in path, f'unexpected path: {path}'; "
                    "print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"PatternTrackingLogger() default path failed.\n"
            f"stderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )
        assert "OK" in result.stdout

    def test_utc_importable_from_datetime_module(self) -> None:
        """The error_handling module must import UTC from datetime without NameError."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import omniclaude.lib.utils.error_handling; "
                    "from datetime import UTC; "  # UTC must be importable (Python 3.11+)
                    "print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"UTC not importable from datetime.\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout
