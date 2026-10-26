# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21429 AC3: the unused E2 lock and its registrations stay deleted."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
# Split the retired name so the tracked-reference assertion does not match itself.
RETIRED_MODULE = "preexisting" + "_fix_lock"


class TestE2LockRetirement(unittest.TestCase):
    def test_module_and_old_unit_test_are_absent(self) -> None:
        for relative_path in (
            f"plugins/onex/hooks/lib/{RETIRED_MODULE}.py",
            f"tests/unit/hooks/lib/test_{RETIRED_MODULE}.py",
        ):
            with self.subTest(path=relative_path):
                path = REPO_ROOT / relative_path
                self.assertFalse(path.exists() or path.is_symlink(), relative_path)

    def test_no_tracked_reference_outside_contracts(self) -> None:
        result = subprocess.run(
            [
                "git",
                "grep",
                "-n",
                "-F",
                "-e",
                RETIRED_MODULE,
                "--",
                ".",
                ":!contracts/",
            ],
            cwd=REPO_ROOT,
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
