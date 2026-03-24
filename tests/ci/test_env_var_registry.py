# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI guard: every os.getenv/os.environ reference in production code
must be registered in .env.example (OMN-6260)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
class TestEnvVarRegistry:
    def test_scanner_output_has_required_keys(self) -> None:
        """Scanner JSON output must contain registered, unregistered, allowlisted keys."""
        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci/check_env_var_registry.py",
                "--scan-dirs",
                "src/omniclaude",
                "plugins/onex/hooks/lib",
                "--registry",
                ".env.example",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        data = json.loads(result.stdout)
        assert "unregistered" in data
        assert "registered" in data
        assert "allowlisted" in data
        # registered should contain known vars from .env.example
        assert "KAFKA_BOOTSTRAP_SERVERS" in data["registered"]

    def test_scanner_exits_zero_when_clean(self, tmp_path: Path) -> None:
        """Scanner exits 0 when all referenced vars are in the registry."""
        # Create minimal .env.example with one var
        registry = tmp_path / ".env.example"
        registry.write_text("MY_VAR=default\n")

        # Create minimal Python file referencing that var
        scan_dir = tmp_path / "src"
        scan_dir.mkdir()
        (scan_dir / "app.py").write_text('import os\nv = os.getenv("MY_VAR")\n')

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts/ci/check_env_var_registry.py"),
                "--scan-dirs",
                str(scan_dir),
                "--registry",
                str(registry),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0

    def test_scanner_exits_one_when_gap_found(self, tmp_path: Path) -> None:
        """Scanner exits 1 when a referenced var is not in the registry."""
        registry = tmp_path / ".env.example"
        registry.write_text("REGISTERED_VAR=yes\n")

        scan_dir = tmp_path / "src"
        scan_dir.mkdir()
        (scan_dir / "app.py").write_text(
            'import os\nv = os.getenv("UNREGISTERED_VAR")\n'
        )

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts/ci/check_env_var_registry.py"),
                "--scan-dirs",
                str(scan_dir),
                "--registry",
                str(registry),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
