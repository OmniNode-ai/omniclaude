# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the node-identity bare-name-keying checker (OMN-14584).

Proves the checker actually flags the two real incident shapes
(OMN-14575's dict comprehension, a subscript-assignment equivalent) and does
not flag a properly package-qualified key — the fast, author-time gate for
the disease behind OMN-10865/OMN-14571/OMN-14575.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from check_node_identity_keying import _check_file  # noqa: E402

pytestmark = [pytest.mark.unit]


def test_flags_dict_comprehension_bare_name_keying(tmp_path: Path) -> None:
    """OMN-14575's exact shape: by_name = {n.name: n for n in graph.nodes}."""
    source = "by_name = {n.name: n for n in graph.nodes}\n"
    file_path = tmp_path / "sample.py"
    file_path.write_text(source)

    violations = _check_file(file_path)

    assert len(violations) == 1
    assert violations[0].line == 1


def test_flags_subscript_assignment_bare_name_keying(tmp_path: Path) -> None:
    """The assignment-in-loop equivalent: for n in nodes: by_name[n.name] = n."""
    source = "for n in nodes:\n    by_name[n.name] = n\n"
    file_path = tmp_path / "sample.py"
    file_path.write_text(source)

    violations = _check_file(file_path)

    assert len(violations) == 1
    assert violations[0].line == 2


def test_does_not_flag_package_qualified_keying(tmp_path: Path) -> None:
    """A properly qualified key (f-string, tuple, or any non-bare-attribute
    expression) must not be flagged — this is the fix shape from OMN-14571/
    OMN-14575, not the bug shape."""
    source = (
        'by_name = {f"{n.package}::{n.name}": n for n in graph.nodes}\n'
        "for n in nodes:\n"
        "    by_name[(n.package, n.name)] = n\n"
    )
    file_path = tmp_path / "sample.py"
    file_path.write_text(source)

    violations = _check_file(file_path)

    assert violations == []


def test_suppression_marker_silences_a_flagged_line(tmp_path: Path) -> None:
    source = "by_name = {n.name: n for n in graph.nodes}  # node-identity-keying-ok: test fixture\n"
    file_path = tmp_path / "sample.py"
    file_path.write_text(source)

    violations = _check_file(file_path)

    assert violations == []


def test_unrelated_dict_comprehension_is_not_flagged(tmp_path: Path) -> None:
    """A dict comprehension keyed on something other than `.name` (the
    overwhelming majority of real code) must not be flagged."""
    source = "by_id = {n.node_id: n for n in graph.nodes}\n"
    file_path = tmp_path / "sample.py"
    file_path.write_text(source)

    violations = _check_file(file_path)

    assert violations == []


def test_bare_name_keying_over_non_node_collection_is_not_flagged(
    tmp_path: Path,
) -> None:
    """Keying a dict by bare `.name` is common and entirely benign for
    objects that have nothing to do with ONEX node identity. An unscoped
    first draft of this checker found 6 real hits in this repo, all false
    positives on exactly this shape (LLM model scores, agent registries,
    personality profiles) — this pins the fix."""
    source = (
        "model_scores = {model.name: 0.85 for model in self.models}\n"
        "for agent_def in request.agent_registry:\n"
        "    agents[agent_def.name] = agent_def\n"
        "for profile in extra_profiles:\n"
        "    self._profiles[profile.name] = profile\n"
    )
    file_path = tmp_path / "sample.py"
    file_path.write_text(source)

    violations = _check_file(file_path)

    assert violations == []
