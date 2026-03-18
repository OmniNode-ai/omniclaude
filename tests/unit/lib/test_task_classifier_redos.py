# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""ReDoS regression test for TaskClassifier._extract_entities.

Verifies that the entity extraction regex does not exhibit catastrophic
backtracking on pathological inputs (CWE-1333).

Related: OMN-5415
"""

from __future__ import annotations

import time

import pytest

from omniclaude.lib.task_classifier import TaskClassifier


@pytest.fixture
def classifier() -> TaskClassifier:
    return TaskClassifier()


class TestExtractEntitiesReDoS:
    @pytest.mark.unit
    def test_normal_input(self, classifier: TaskClassifier) -> None:
        """Normal entity extraction still works after fix."""
        result = classifier._extract_entities(
            "Fix node_user_reducer.py and update agent_routing_decisions table"
        )
        assert "node_user_reducer.py" in result
        assert "agent_routing_decisions" in result

    @pytest.mark.unit
    def test_pathological_input_completes_fast(
        self, classifier: TaskClassifier
    ) -> None:
        """Pathological ReDoS input must complete in under 1 second.

        The old pattern r'\\b\\w+(?:_\\w+)*\\.\\w+\\b|\\b\\w+(?:_\\w+)+\\b'
        would catastrophically backtrack on inputs like 'aaa...aaa!' where
        the trailing character forces repeated backtracking across all the
        underscore-free quantifier combinations.
        """
        # Classic ReDoS input: long underscore-free word followed by a non-word
        # boundary character that forces the engine to exhaust all combinations.
        pathological = "a" * 50 + "!"
        start = time.monotonic()
        classifier._extract_entities(pathological)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, (
            f"_extract_entities took {elapsed:.3f}s on pathological input — "
            "likely ReDoS regression"
        )

    @pytest.mark.unit
    def test_repeated_underscore_segments_fast(
        self, classifier: TaskClassifier
    ) -> None:
        """Long identifier with many underscore segments must complete quickly."""
        pathological = "_".join(["segment"] * 40) + "!"
        start = time.monotonic()
        classifier._extract_entities(pathological)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, (
            f"_extract_entities took {elapsed:.3f}s on underscore-heavy input"
        )

    @pytest.mark.unit
    def test_file_extension_entities_extracted(
        self, classifier: TaskClassifier
    ) -> None:
        prompt = "Edit config.yaml and src/foo/bar.py then update models.py"
        result = classifier._extract_entities(prompt)
        assert "config.yaml" in result
        assert "bar.py" in result
        assert "models.py" in result

    @pytest.mark.unit
    def test_underscore_entities_extracted(self, classifier: TaskClassifier) -> None:
        prompt = "The agent_routing_decisions and task_classifier_utils modules"
        result = classifier._extract_entities(prompt)
        assert "agent_routing_decisions" in result
        assert "task_classifier_utils" in result

    @pytest.mark.unit
    def test_returns_sorted_deduped(self, classifier: TaskClassifier) -> None:
        prompt = "foo_bar foo_bar baz.py baz.py"
        result = classifier._extract_entities(prompt)
        assert result.count("foo_bar") == 1
        assert result.count("baz.py") == 1
        assert result == sorted(result)
