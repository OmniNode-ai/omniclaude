#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for CI recovery failure classification heuristics."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import classifier via file path since plugins aren't on sys.path
_CLASSIFIER_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_lib"
    / "ci_recovery"
    / "classifier.py"
)
_spec = importlib.util.spec_from_file_location("classifier", _CLASSIFIER_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["classifier"] = _mod
_spec.loader.exec_module(_mod)
classify_ci_failure = _mod.classify_ci_failure


@pytest.mark.unit
class TestCIFailureClassification:
    """Verify the 4-way classification heuristic from ci_recovery prompt.md."""

    def test_flaky_test_detected_by_known_pattern(self) -> None:
        """Flaky test: test name in known-flaky list."""
        log = "FAILED tests/integration/test_kafka_consumer.py::test_message_ordering - TimeoutError"
        classification = classify_ci_failure(log, known_flaky=["test_message_ordering"])
        assert classification == "flaky_test"

    def test_infra_issue_detected_by_runner_keyword(self) -> None:
        """Infra issue: log contains runner/timeout/network keywords."""
        log = "Error: The self-hosted runner lost connection during the build"
        classification = classify_ci_failure(log, known_flaky=[])
        assert classification == "infra_issue"

    def test_config_error_detected_by_lockfile_keyword(self) -> None:
        """Config error: log contains lock file / version mismatch."""
        log = "error: lock file uv.lock is not up to date with pyproject.toml"
        classification = classify_ci_failure(log, known_flaky=[])
        assert classification == "config_error"

    def test_real_failure_is_default(self) -> None:
        """Real failure: no pattern matches."""
        log = "AssertionError: expected 42 but got 0"
        classification = classify_ci_failure(log, known_flaky=[])
        assert classification == "real_failure"

    def test_infra_keywords_are_case_insensitive(self) -> None:
        """Infra detection is case-insensitive."""
        log = "Connection Refused on port 5432"
        classification = classify_ci_failure(log, known_flaky=[])
        assert classification == "infra_issue"
